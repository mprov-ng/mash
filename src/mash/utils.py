
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


def rangeToList(teststr):
  # find the opening of the range
  rangeStart = teststr.find('[')

  if rangeStart < 0:
    # only one node.
    return [teststr]

  prefix = teststr[0:rangeStart]
  tmpList = []

  teststr = teststr[rangeStart:]
  # find the next comma
  nextRangeEnd = teststr.find(',')
  if nextRangeEnd < 0:
    # try to see if the end of the range is reached.
    nextRangeEnd = teststr.find(']')
    if nextRangeEnd < 0:
      # someone dun goofed.  The rang is invalid.
      raise Exception("Range Invalid, no closing bracket found")

  while(nextRangeEnd > -1):
    # do we have a range or a single number
    nodeRange = teststr[1:nextRangeEnd]
    rangeSpecifier = nodeRange.find('-')
    if rangeSpecifier < 0:
      # no range, just append this node.
      tmpList.append(f"{prefix}{nodeRange}")
    else:
      # found a range specifier
      intLen = len(nodeRange[:rangeSpecifier])
      start = int(nodeRange[:rangeSpecifier])
      end = int(nodeRange[rangeSpecifier+1:nextRangeEnd]) +1
      # check if we accidentally overflow intLen
      if len(str(end-1).zfill(intLen)) > intLen:
        raise Exception("Range Format Error, padded zeros do not match range.")
      for nodeNum in range(start,end):
        nodeNumStr = str(nodeNum).zfill(intLen)
        tmpList.append(f"{prefix}{nodeNumStr}")
    teststr = teststr[nextRangeEnd+1:]
    if teststr == "":
      break
    nextRangeEnd = teststr.find(',')
    if nextRangeEnd < 0:
      # try to see if the end of the range is reached.
      nextRangeEnd = teststr.find(']')
      if nextRangeEnd < 0:
        # someone dun goofed.  The rang is invalid.
        raise Exception("Range Invalid, no closing bracket found")

  return tmpList
