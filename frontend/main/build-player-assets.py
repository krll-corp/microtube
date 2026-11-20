import sys
import tarfile
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

url = "https://registry.npmjs.org/hls.js/-/hls.js-1.7.4.tgz"
with urlopen(url, timeout=40) as response:
    archive = response.read()
if sha256(archive).hexdigest() != "e4ab3d5d13f7cca9ef241d098f39686e19fd451831ba07dc9943482fd5ff75c7":
    raise RuntimeError("Unexpected hls.js package checksum")

destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as package:
    for entry, name in (("dist/hls.light.min.js", "hls.js"), ("LICENSE", "hls.LICENSE.txt")):
        with package.extractfile("package/" + entry) as file:
            (destination / name).write_bytes(file.read())
