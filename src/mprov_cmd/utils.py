
def getDottedStrValue(dstring, obj):
  """
  Gets the value on the object, which may be a nested object,
  of the path specified in dstring

  """
  objcpy = obj
  keys = dstring.split(".")
  for key in keys:
      objcpy = objcpy[key]
  return objcpy