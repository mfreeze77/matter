"""Private, immutable external evaluation artifacts, separate from core records."""
import os
import tempfile
from pathlib import Path
from ..canonical import canonical_bytes,loads,source_digest
from ..contracts import ContractError


class ArtifactDirectory:
    """Host-selected destination. Append-only flat names; no secret configuration."""
    def __init__(self,path,*,resume=False):
        self.path=Path(path)
        if resume:
            if not self.path.is_dir() or self.path.is_symlink():raise ContractError('E_STORAGE_UNAVAILABLE')
        else:self.path.mkdir(mode=0o700,parents=False,exist_ok=False)
    def _path(self,name):
        if type(name) is not str or not name or '/' in name or '\\' in name or name in ('.','..'):raise ContractError('E_SCHEMA_INVALID')
        return self.path/name
    def write(self,name,value):
        data=canonical_bytes(value)+b'\n';path=self._path(name)
        descriptor,temporary=tempfile.mkstemp(prefix='.pending-',dir=self.path)
        try:
            with os.fdopen(descriptor,'wb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            # Atomic append-only publication: a killed writer can leave a private
            # pending file, but cannot expose torn bytes under a final name.
            os.link(temporary,path)
        finally:
            os.unlink(temporary)
        if os.name!='nt':
            directory=os.open(self.path,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        return {'reference':name,'sha256':source_digest(data),'byte_length':len(data)}
    def read(self,name):
        path=self._path(name)
        if path.is_symlink():raise ContractError('E_STORAGE_UNAVAILABLE')
        return loads(path.read_bytes())
    def exists(self,name):return self._path(name).exists()
