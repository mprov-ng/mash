from setuptools import setup
import os, sys
if __name__ == '__main__':
    version=""
    with open('requirements.txt') as f:
        requirements = f.readlines()
    if os.path.exists('VERSION'):
        with open('VERSION') as v:
            version = v.read()
    else:
        if "MASH_VERSION" in os.environ:
          version = os.environ['MASH_VERSION']
        else:
          print(f"Error: Please specify your build version via MASH_VERSION environment variable or in a VERSION file.")
          sys.exit(1)
    setup(version=version, install_requires=requirements)
