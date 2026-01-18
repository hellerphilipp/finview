import yaml
import cel 
from .schema import ImporterMapping

class CSVImporter:
    def __init__(self, yaml_path: str):
        with open(yaml_path, 'r') as f:
            raw_config = yaml.safe_load(f)
            self.config = ImporterMapping(**raw_config)

    def parse_row(self, row: list[str]) -> dict:
        # Define helpers that the YAML expressions need
        def double(val):
            if not val or str(val).strip() == "": 
                return 0.0
            return float(str(val).replace(',', '.'))

        # We pass Python's split as a function named 'split'
        context = {
            "row": row,
            "double": double,
            "split": lambda s, d: s.split(d)
        }

        results = {}
        for field, expr_str in self.config.mappings.model_dump().items():
            try:
                # Use the direct evaluate function provided by the 'cel' module
                results[field] = cel.evaluate(expr_str, context)
            except Exception as e:
                raise ValueError(f"Error evaluating field '{field}': {e}")
                
        return results