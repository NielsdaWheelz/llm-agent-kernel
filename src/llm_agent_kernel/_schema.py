"""Compile result schemas into the Codex Structured Outputs subset."""

from __future__ import annotations

from collections.abc import Mapping


class UnsupportedStructuredOutputError(ValueError):
    """A logical structured result cannot be represented on the provider wire."""


_ANNOTATION_KEYS = frozenset({"default", "discriminator", "examples", "title"})
_SUPPORTED_KEYS = frozenset(
    {
        "$defs",
        "$ref",
        "additionalProperties",
        "anyOf",
        "const",
        "description",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "items",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "multipleOf",
        "pattern",
        "properties",
        "required",
        "type",
    }
)
_SUPPORTED_TYPES = frozenset({"array", "boolean", "integer", "null", "number", "object", "string"})
_SUPPORTED_FORMATS = frozenset(
    {"date", "date-time", "duration", "email", "hostname", "ipv4", "ipv6", "time", "uuid"}
)
_MAX_OBJECT_PROPERTIES = 5_000
_MAX_OBJECT_DEPTH = 10
_WIRE_ENVELOPE_OBJECT_DEPTH = 2
_MAX_SCHEMA_STRING_BYTES = 120_000
_MAX_ENUM_VALUES = 1_000
_MAX_LARGE_ENUM_STRING_BYTES = 15_000


def compile_structured_result_schema(schema: Mapping[str, object]) -> dict[str, object]:
    """Normalize one closed object schema for Codex or reject it deterministically.

    Pydantic uses omission plus ``default`` for optional fields. Codex strict
    schemas require every property, so compilation makes every object property
    required and removes non-validating generator annotations. Nested ``oneOf``
    is lowered to the supported ``anyOf``; the kernel's independent Pydantic
    validation retains the exact logical semantics.
    """

    if not isinstance(schema, Mapping):
        raise UnsupportedStructuredOutputError("structured output schema must be an object")
    compiled = _compile_node(schema, path="$", object_depth=_WIRE_ENVELOPE_OBJECT_DEPTH)
    if compiled.get("type") != "object":
        raise UnsupportedStructuredOutputError(
            "structured output root must be a directly declared object"
        )
    _require_references_and_depth(compiled)
    _require_schema_limits(compiled)
    return compiled


def _compile_node(
    node: Mapping[str, object],
    *,
    path: str,
    object_depth: int,
) -> dict[str, object]:
    unknown = set(node).difference(_SUPPORTED_KEYS, _ANNOTATION_KEYS, {"oneOf"})
    if unknown:
        names = ", ".join(sorted(unknown))
        raise UnsupportedStructuredOutputError(
            f"structured output schema uses unsupported keyword(s) at {path}: {names}"
        )
    if "oneOf" in node and "anyOf" in node:
        raise UnsupportedStructuredOutputError(
            f"structured output schema mixes oneOf and anyOf at {path}"
        )

    result: dict[str, object] = {}
    for key, value in node.items():
        if key in _ANNOTATION_KEYS or key in {"properties", "required", "$defs", "items"}:
            continue
        if key in {"anyOf", "oneOf"}:
            if not isinstance(value, list) or not value:
                raise UnsupportedStructuredOutputError(
                    f"structured output {key} must be a non-empty array at {path}"
                )
            variants: list[object] = []
            for index, variant in enumerate(value):
                if not isinstance(variant, Mapping):
                    raise UnsupportedStructuredOutputError(
                        f"structured output {key} member is not a schema at {path}[{index}]"
                    )
                variants.append(
                    _compile_node(
                        variant,
                        path=f"{path}.{key}[{index}]",
                        object_depth=object_depth,
                    )
                )
            result["anyOf"] = variants
            continue
        result[key] = value

    schema_type = node.get("type")
    declared_types: tuple[object, ...]
    if isinstance(schema_type, list):
        declared_types = tuple(schema_type)
    elif schema_type is None:
        declared_types = ()
    else:
        declared_types = (schema_type,)
    if any(type(item) is not str or item not in _SUPPORTED_TYPES for item in declared_types):
        raise UnsupportedStructuredOutputError(
            f"structured output schema has an unsupported type at {path}"
        )
    schema_format = node.get("format")
    if schema_format is not None and schema_format not in _SUPPORTED_FORMATS:
        raise UnsupportedStructuredOutputError(
            f"structured output schema has an unsupported format at {path}: {schema_format}"
        )

    is_object = "object" in declared_types or any(
        key in node for key in ("properties", "required", "additionalProperties")
    )
    if is_object:
        next_depth = object_depth + 1
        if next_depth > _MAX_OBJECT_DEPTH:
            raise UnsupportedStructuredOutputError(
                f"structured output schema exceeds {_MAX_OBJECT_DEPTH} object levels at {path}"
            )
        properties = node.get("properties")
        if not isinstance(properties, Mapping) or any(type(key) is not str for key in properties):
            raise UnsupportedStructuredOutputError(
                f"structured output object must declare named properties at {path}"
            )
        if node.get("additionalProperties") is not False:
            raise UnsupportedStructuredOutputError(
                f"structured output object must set additionalProperties=false at {path}"
            )
        original_required = node.get("required", [])
        if not isinstance(original_required, list) or any(
            type(item) is not str for item in original_required
        ):
            raise UnsupportedStructuredOutputError(
                f"structured output required must be an array of names at {path}"
            )
        extra_required = set(original_required).difference(properties)
        if extra_required:
            names = ", ".join(sorted(extra_required))
            raise UnsupportedStructuredOutputError(
                f"structured output object has unknown required name(s) at {path}: {names}"
            )
        compiled_properties: dict[str, object] = {}
        for name, child in properties.items():
            if not isinstance(child, Mapping):
                raise UnsupportedStructuredOutputError(
                    f"structured output property is not a schema at {path}.{name}"
                )
            compiled_properties[name] = _compile_node(
                child,
                path=f"{path}.properties.{name}",
                object_depth=next_depth,
            )
        result["properties"] = compiled_properties
        result["required"] = list(compiled_properties)
        result["additionalProperties"] = False

    if "items" in node:
        items = node["items"]
        if not isinstance(items, Mapping):
            raise UnsupportedStructuredOutputError(
                f"structured output array items must be one schema at {path}"
            )
        result["items"] = _compile_node(
            items,
            path=f"{path}.items",
            object_depth=object_depth,
        )

    if "$defs" in node:
        definitions = node["$defs"]
        if not isinstance(definitions, Mapping) or any(
            type(name) is not str for name in definitions
        ):
            raise UnsupportedStructuredOutputError(
                f"structured output $defs must contain named schemas at {path}"
            )
        compiled_definitions: dict[str, object] = {}
        for name, child in definitions.items():
            if not isinstance(child, Mapping):
                raise UnsupportedStructuredOutputError(
                    f"structured output definition is not a schema at {path}.$defs.{name}"
                )
            compiled_definitions[name] = _compile_node(
                child,
                path=f"{path}.$defs.{name}",
                object_depth=object_depth,
            )
        result["$defs"] = compiled_definitions

    return result


def _require_references_and_depth(schema: Mapping[str, object]) -> None:
    raw_definitions = schema.get("$defs", {})
    definitions = raw_definitions if isinstance(raw_definitions, Mapping) else {}
    visited: set[str] = set()

    def visit(node: object, object_depth: int, active_refs: frozenset[str]) -> None:
        if not isinstance(node, Mapping):
            return
        reference = node.get("$ref")
        if reference is not None:
            if type(reference) is not str or not reference.startswith("#/$defs/"):
                raise UnsupportedStructuredOutputError(
                    "structured output schema uses an unsupported reference"
                )
            name = reference.removeprefix("#/$defs/")
            target = definitions.get(name)
            if not name or not isinstance(target, Mapping):
                raise UnsupportedStructuredOutputError(
                    f"structured output schema references an unknown definition: {reference}"
                )
            visited.add(name)
            if name not in active_refs:
                visit(target, object_depth, active_refs | {name})

        schema_type = node.get("type")
        types = schema_type if isinstance(schema_type, list) else [schema_type]
        next_depth = object_depth
        if "object" in types or "properties" in node:
            next_depth += 1
            if next_depth > _MAX_OBJECT_DEPTH:
                raise UnsupportedStructuredOutputError(
                    f"structured output schema exceeds {_MAX_OBJECT_DEPTH} object levels"
                )
        properties = node.get("properties")
        if isinstance(properties, Mapping):
            for child in properties.values():
                visit(child, next_depth, active_refs)
        items = node.get("items")
        if isinstance(items, Mapping):
            visit(items, next_depth, active_refs)
        variants = node.get("anyOf")
        if isinstance(variants, list):
            for child in variants:
                visit(child, next_depth, active_refs)

    visit(schema, _WIRE_ENVELOPE_OBJECT_DEPTH, frozenset())
    for name, definition in definitions.items():
        if name not in visited:
            visit(definition, _WIRE_ENVELOPE_OBJECT_DEPTH, frozenset({name}))


def _require_schema_limits(schema: Mapping[str, object]) -> None:
    property_count = 0
    string_bytes = 0
    enum_count = 0

    def walk(node: object) -> None:
        nonlocal property_count, string_bytes, enum_count
        if isinstance(node, Mapping):
            properties = node.get("properties")
            if isinstance(properties, Mapping):
                property_count += len(properties)
                string_bytes += sum(len(name.encode("utf-8")) for name in properties)
            definitions = node.get("$defs")
            if isinstance(definitions, Mapping):
                string_bytes += sum(len(name.encode("utf-8")) for name in definitions)
            enum = node.get("enum")
            if isinstance(enum, list):
                enum_count += len(enum)
                enum_string_bytes = sum(
                    len(value.encode("utf-8")) for value in enum if isinstance(value, str)
                )
                string_bytes += enum_string_bytes
                if len(enum) > 250 and enum_string_bytes > _MAX_LARGE_ENUM_STRING_BYTES:
                    raise UnsupportedStructuredOutputError(
                        "structured output schema exceeds the large-enum string limit"
                    )
            const = node.get("const")
            if isinstance(const, str):
                string_bytes += len(const.encode("utf-8"))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)
    if property_count > _MAX_OBJECT_PROPERTIES:
        raise UnsupportedStructuredOutputError(
            "structured output schema exceeds the object-property limit"
        )
    if string_bytes > _MAX_SCHEMA_STRING_BYTES:
        raise UnsupportedStructuredOutputError("structured output schema exceeds the string limit")
    if enum_count > _MAX_ENUM_VALUES:
        raise UnsupportedStructuredOutputError("structured output schema exceeds the enum limit")


__all__ = ["UnsupportedStructuredOutputError", "compile_structured_result_schema"]
