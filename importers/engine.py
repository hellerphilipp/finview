import yaml
import cel
from .schema import ImporterMapping


def _double(val):
    if not val or str(val).strip() == "":
        return 0.0
    return float(str(val).replace(",", "."))


def _split(s, d):
    return s.split(d)


class CSVImporter:
    def __init__(self, yaml_path: str):
        with open(yaml_path, 'r') as f:
            raw_config = yaml.safe_load(f)
            self.config = ImporterMapping(**raw_config)

    def parse_row(self, row: list[str]) -> dict:
        context = {
            "row": row,
            "double": _double,
            "split": _split,
        }

        results = {}
        for field, expr_str in self.config.mappings.model_dump().items():
            try:
                results[field] = cel.evaluate(expr_str, context)
            except Exception as e:
                raise ValueError(f"Error evaluating field '{field}': {e}")

        return results
