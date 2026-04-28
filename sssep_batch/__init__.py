"""Public package entry point for the SSSEP batch processor.

Most users never import this package directly; they run
`sssep_bdf_batch_processor.py` from PyCharm. The `main()` function exists so
other Python code can still start a config-driven batch run if needed.
"""

def main():
    """Run the batch processor using fallback folders from `config.py`."""
    from sssep_batch.batch import main as batch_main

    return batch_main()

__all__ = ["main"]
