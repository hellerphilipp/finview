from pydantic import BaseModel, ConfigDict

class ParserConfig(BaseModel):
    delimiter: str
    skip_rows: int

class DataMapping(BaseModel):
    timestamp: str
    description: str
    amount_original: str
    currency_original: str
    amount_in_account_currency: str

class ImporterMapping(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    version: str
    name: str
    parser: ParserConfig
    mappings: DataMapping