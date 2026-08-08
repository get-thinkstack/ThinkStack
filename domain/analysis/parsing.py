"""shape coercion for small-model json.

the gbnf grammar guarantees the model emits *valid* json. it does not
guarantee the *right* json, and the two are routinely confused. asked for

    {"claims": [{"claim_text": ..., "claim_type": ...}]}

a small model will cheerfully return ``{"claims": ["first claim", ...]}``, or
``[{...}]`` with no wrapper key, or ``{"claim": {...}}`` singular. every one of
those is valid json and every one of those used to break a caller:

  * ``item.get(...)`` on a string raised AttributeError -- and in
    document_analysis and gap_pipeline that call sits OUTSIDE the try block
    that was meant to contain parse failures, so it escaped as a 500.
  * ``data.get("claims", [])`` on a bare list returned ``[]``, which is
    indistinguishable from "this paper genuinely has no claims".

the helpers here take the ungenerous view that any of those shapes may arrive,
and recover the content rather than discarding it. a claim the model wrote as a
bare string is still a claim; throwing it away to keep the parser tidy loses
the user's work for no reason.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def as_items(data: Any, key: str) -> list:
    """pull the list named ``key`` out of a parsed model response.

    accepts the response being the list itself (no wrapper object), the key
    being present, or a singular form of the key. returns [] when there is
    genuinely nothing, having logged what arrived instead.

    args:
        data: the parsed json from the model.
        key: the plural key the prompt asked for, e.g. "claims".

    returns:
        a list -- possibly empty, never None.
    """
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        logger.warning("model returned %s, expected an object or list", type(data).__name__)
        return []

    for candidate in (key, key.rstrip("s"), f"{key}_list"):
        value = data.get(candidate)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            # singular object where a list was asked for -- one item.
            return [value]

    # last resort: exactly one list-valued field, whatever it is called.
    lists = [v for v in data.values() if isinstance(v, list)]
    if len(lists) == 1:
        logger.info("model used an unexpected key for %r; recovered by shape", key)
        return lists[0]

    logger.warning("no list found for %r in model output (keys: %s)", key, list(data))
    return []


def as_dict(item: Any, text_key: str) -> dict:
    """normalise one entry of a model list into a dict.

    a bare string becomes ``{text_key: item}`` rather than being dropped: the
    string IS the content the prompt asked for, just without the envelope.

    args:
        item: one entry from a model-produced list.
        text_key: the field a bare string should be assigned to.

    returns:
        a dict, always. entries that are neither dict nor string yield {}.
    """
    if isinstance(item, dict):
        return item
    if isinstance(item, str):
        return {text_key: item}
    logger.warning("dropping %s entry in model list", type(item).__name__)
    return {}


def one_of(value: Any, allowed: tuple[str, ...], default: str) -> str:
    """constrain a model-supplied enum to the values the app actually handles.

    an invented category is not harmless: it reaches the canvas as a node
    label and the ui as a filter value that matches nothing.

    args:
        value: whatever the model put in the field.
        allowed: the permitted values.
        default: what to use when the model's value is not one of them.

    returns:
        a member of ``allowed``.
    """
    if isinstance(value, str):
        v = value.strip().lower().replace(" ", "_").replace("-", "_")
        if v in allowed:
            return v
    if value not in (None, ""):
        logger.info("model returned %r, not one of %s; using %r", value, allowed, default)
    return default


def as_str_list(value: Any) -> list[str]:
    """coerce a field that should be a list of strings.

    a single string becomes a one-element list -- models drop the brackets when
    there is only one item.
    """
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v not in (None, "")]
