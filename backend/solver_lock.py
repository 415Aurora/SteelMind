"""One lock for every adapter using OpenSees process-global state."""
from threading import RLock
OPENSEES_LOCK=RLock()
