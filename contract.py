"""Shared contract loading and response verification (OpenAPI 3.0 nullable support)."""
from base64 import b64decode
from hashlib import sha256
from pathlib import Path

from ruamel.yaml import YAML
from jsonschema import Draft7Validator, FormatChecker


def load_contract(path):
    return YAML(typ="safe", pure=True).load(Path(path).read_text(encoding="utf-8"))


def json_schema(value):
    if isinstance(value, list):
        return [json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: json_schema(item) for key, item in value.items() if key != "nullable"}
    if value.get("nullable") and isinstance(result.get("type"), str):
        result["type"] = [result["type"], "null"]
    return result


def validate_payload(contract, schema_name, payload):
    schema = {"$ref": f"#/components/schemas/{schema_name}", "components": json_schema(contract["components"])}
    errors = [f"{'/'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
              for error in Draft7Validator(schema, format_checker=FormatChecker()).iter_errors(payload)]
    if not errors and schema_name == "SystemReport":
        code = payload["coverage"]["code"]
        covered, total = code["covered"], code["total"]
        if (covered is None) != (total is None) or (covered is not None and covered > total):
            errors.append("coverage/code: counts must both be null or satisfy covered <= total")
    if not errors and schema_name == "EvaluationResult":
        for key in ("output_pdf", "report_pdf"):
            try:
                data = b64decode(payload[key]["content_base64"], validate=True)
                if not data.startswith(b"%PDF-") or sha256(data).hexdigest() != payload[key]["sha256"]:
                    errors.append(f"{key}: invalid PDF bytes or SHA-256")
            except (ValueError, TypeError):
                errors.append(f"{key}: invalid Base64")
    return errors
