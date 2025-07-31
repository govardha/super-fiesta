import collections.abc
import json


def to_dict(obj):
    return json.loads(
        json.dumps(
            obj,
            default=lambda o: dict(
                (key, value) for key, value in o.__dict__.items() if value
            ),
            indent=4,
            allow_nan=False,
        )
    )


def update(d, u):
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = update(d.get(k, {}), v)
        else:
            d[k] = v
    return d
