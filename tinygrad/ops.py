import numpy as np
from .tensor import Function, register

# ************* basic ops *************

class Add(Function):
  @staticmethod
  def forward(ctx, x, y):
    return x+y

  @staticmethod
  def backward(ctx, grad_output):
    return grad_output, grad_output
register('add', Add)

class Sub(Function):
  @staticmethod
  def forward(ctx, x, y):
    return x-y

  @staticmethod
  def backward(ctx, grad_output):
    # this right?
    return grad_output, -grad_output
register('sub', Sub)

class Mul(Function):
  @staticmethod
  def forward(ctx, x, y):
    ctx.save_for_backward(x, y)
    return x*y

  @staticmethod
  def backward(ctx, grad_output):
    x,y = ctx.saved_tensors
    return y*grad_output, x*grad_output
register('mul', Mul)

class Pow(Function):
  @staticmethod
  def forward(ctx, x, y):
    ctx.save_for_backward(x, y)
    return x ** y

  @staticmethod
  def backward(ctx, grad_output):
    x,y = ctx.saved_tensors
    return y * (x**(y-1.0)) * grad_output, (x**y) * np.log(x) * grad_output
register('pow', Pow)

class Sum(Function):
  @staticmethod
  def forward(ctx, input):
    ctx.save_for_backward(input)
    return np.array([input.sum()])

  @staticmethod
  def backward(ctx, grad_output):
    input, = ctx.saved_tensors
    return grad_output * np.ones_like(input)
register('sum', Sum)


# ************* GEMM *************

class Dot(Function):
  @staticmethod
  def forward(ctx, input, weight):
    ctx.save_for_backward(input, weight)
    return input.dot(weight)

  @staticmethod
  def backward(ctx, grad_output):
    input, weight = ctx.saved_tensors
    grad_input = grad_output.dot(weight.T)
    grad_weight = input.T.dot(grad_output)
    return grad_input, grad_weight
register('dot', Dot)
register('matmul', Dot)


# ************* simple ops *************

class Pad2D(Function):
  @staticmethod
  def forward(ctx, x, padding=None):
    return np.pad(x,
      ((0,0), (0,0),
       (padding[0], padding[1]), (padding[2], padding[3])))

  @staticmethod
  def backward(ctx, grad_output):
    raise Exception("write this")
register('pad2d', Pad2D)

class Reshape(Function):
  @staticmethod
  def forward(ctx, x, shape):
    ctx.save_for_backward(x.shape)
    return x.reshape(shape)

  @staticmethod
  def backward(ctx, grad_output):
    in_shape, = ctx.saved_tensors
    return grad_output.reshape(in_shape)
register('reshape', Reshape)


# ************* activation ops *************

class ReLU(Function):
  @staticmethod
  def forward(ctx, input):
    ctx.save_for_backward(input)
    return np.maximum(input, 0)

  @staticmethod
  def backward(ctx, grad_output):
    input, = ctx.saved_tensors
    grad_input = grad_output * (input >= 0)
    return grad_input
register('relu', ReLU)

class Sigmoid(Function):
  @staticmethod
  def forward(ctx, input):
    # TODO: stable sigmoid? does the overflow matter?
    with np.warnings.catch_warnings():
      np.warnings.filterwarnings('ignore')
      ret = 1/(1 + np.exp(-input))
    ctx.save_for_backward(ret)
    return ret

  @staticmethod
  def backward(ctx, grad_output):
    ret, = ctx.saved_tensors
    grad_input = grad_output * (ret * (1 - ret))
    return grad_input
register('sigmoid', Sigmoid)

class LogSoftmax(Function):
  @staticmethod
  def forward(ctx, input):
    def logsumexp(x):
      #return np.log(np.exp(x).sum(axis=1))
      c = x.max(axis=1)
      return c + np.log(np.exp(x-c.reshape((-1, 1))).sum(axis=1))
    output = input - logsumexp(input).reshape((-1, 1))
    ctx.save_for_backward(output)
    return output

  @staticmethod
  def backward(ctx, grad_output):
    output, = ctx.saved_tensors
    return grad_output - np.exp(output)*grad_output.sum(axis=1).reshape((-1, 1))
register('logsoftmax', LogSoftmax)


# ************* conv ops *************

class Conv2D(Function):
  @staticmethod
  def forward(ctx, x, w, stride=1, groups=1):
    if type(ctx.stride) == int:
      ctx.stride = (ctx.stride, ctx.stride)
    cout,cin,H,W = w.shape
    ys,xs = ctx.stride
    bs,cin_ = x.shape[0], x.shape[1]
    oy,ox = (x.shape[2]-(H-ys))//ys, (x.shape[3]-(W-xs))//xs
    assert cin*ctx.groups == cin_
    assert cout % ctx.groups == 0
    rcout = cout//ctx.groups

    gx = x.reshape(bs,ctx.groups,cin,x.shape[2],x.shape[3])
    tx = np.lib.stride_tricks.as_strided(gx,
           shape=(bs, ctx.groups, cin, oy, ox, H, W),
           strides=(gx.strides[0], gx.strides[1], gx.strides[2],
                    gx.strides[3]*ys, gx.strides[4]*xs,
                    gx.strides[3], gx.strides[4]),
           writeable=False,
         )
    tx = np.ravel(tx).reshape(tx.shape)
    tw = w.reshape(ctx.groups, rcout, cin, H, W)
    ctx.save_for_backward(tx, tw, x.shape)
    return np.einsum('igjYXyx,gkjyx -> igkYX', tx, tw).reshape(bs, cout, oy, ox)

  @staticmethod
  def backward(ctx, grad_output):
    bs,_,oy,ox = grad_output.shape
    tx, tw, x_shape = ctx.saved_tensors
    _,rcout,cin,H,W = tw.shape
    ys,xs = ctx.stride
    OY,OX = x_shape[2:4]

    ggg = grad_output.reshape(bs,ctx.groups,rcout,oy,ox)
    gdw = np.einsum('igkYX,igjYXyx -> gkjyx',ggg,tx)
   
    #needs to be optimized
    gdx = np.zeros((bs,ctx.groups,cin,OY,OX), dtype=tx.dtype)
    for Y in range(grad_output.shape[2]):
      for X in range(grad_output.shape[3]):
        iY,iX = Y*ys, X*xs
        gdx[:,:,: , iY:iY+H, iX:iX+W] += np.einsum('igk,gkjyx->igjyx',ggg[:,:,:,Y,X], tw)

    return gdx.reshape((bs, ctx.groups*cin, OY, OX)), gdw.reshape((ctx.groups*rcout, cin, H, W))
register('conv2d', Conv2D)


# ************* pooling ops *************

def stack_for_pool(x, py, px):
  my, mx = (x.shape[2]//py)*py, (x.shape[3]//px)*px
  stack = []
  xup = x[:, :, :my, :mx]
  for Y in range(py):
    for X in range(px):
      stack.append(xup[:, :, Y::py, X::px][None])
  return np.concatenate(stack, axis=0)

def unstack_for_pool(fxn, s, py, px):
  my, mx = (s[2]//py)*py, (s[3]//px)*px
  for Y in range(py):
    for X in range(px):
      ll = fxn(Y*px+X)
      if X == 0 and Y == 0:
        ret = np.zeros(s, dtype=ll.dtype)
      ret[:, :, Y:my:py, X:mx:px] = ll
  return ret

class MaxPool2D(Function):
  @staticmethod
  def forward(ctx, x, kernel_size=(2, 2)):
    stack = stack_for_pool(x, *kernel_size)
    idxs = np.argmax(stack, axis=0)
    ctx.save_for_backward(idxs, x.shape)
    return np.max(stack, axis=0)

  @staticmethod
  def backward(ctx, grad_output):
    idxs,s = ctx.saved_tensors
    return unstack_for_pool(
      lambda idx: grad_output * (idxs == idx),
      s, *ctx.kernel_size)
register('max_pool2d', MaxPool2D)

class AvgPool2D(Function):
  @staticmethod
  def forward(ctx, x, kernel_size=(2, 2)):
    stack = stack_for_pool(x, *kernel_size)
    ctx.save_for_backward(x.shape)
    return np.mean(stack, axis=0)

  @staticmethod
  def backward(ctx, grad_output):
    s, = ctx.saved_tensors
    py, px = ctx.kernel_size
    return unstack_for_pool(
      lambda idx: grad_output/py/px,
      s, py, px)
register('avg_pool2d', AvgPool2D)

