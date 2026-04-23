"""SSSEP batch processor package."""

def main():
    """Run the batch processor using fallback folders from `config.py`."""
    from sssep_batch.batch import main as batch_main

    return batch_main()

__all__ = ["main"]
