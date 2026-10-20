"""Internal gated producer/guardian entrypoint; invoked with the active Python."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == '__main__':
    if sys.argv[1:] == ['gate']:
        from evidence.producer_runtime import gate
        sys.exit(gate())
    from evidence.producer import _guardian
    sys.exit(_guardian())
