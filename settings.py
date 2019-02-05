import yaml
import os


class Settings:
    def __init__(self, fn):
        self._fn = fn
        if os.path.isfile(fn):
            with open(fn) as f:
                self._data = yaml.load(f)
        else:
            self._data = {}

    def _write_yaml(self):
        with open(self._fn, 'w') as f:
            yaml.dump(self._data, f, default_flow_style=False)

    def __len__(self):
        return len(self._data)

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value
        self._write_yaml()

    def __delitem__(self, key):
        del self._data[key]
        self._write_yaml()

    def __iter__(self):
        yield from self._data

    def __contains__(self, item):
        return item in self._data

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"<{self.__class__.__name__}: {repr(self._data)}>"
