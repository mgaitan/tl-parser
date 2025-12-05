# `tl-parser`

`tl` is a fast HTML parser written in pure Rust.

This repo provides Python bindings for [`astral-tl`](https://github.com/astral-sh/astral-tl) version, a maintained fork of the original [`y21/tl`](https://github.com/y21/tl) focused on performance, HTML selector coverage, and a stable API.

## Installation

### Pre-built wheels

GitHub releases include wheels for Linux (manylinux x86_64), Windows (x86_64), and macOS (x86_64 + arm64) for Python 3.12–3.14. Download the wheel matching your platform/interpreter and install it with `pip install path/to/tl_parser‑...whl`.

Those wheels are produced by `.github/workflows/python-wheels.yml`, which runs `maturin build -F python` in a matrix covering every OS/architecture/Python combo and attaches the artifacts to the release. Trigger it for a tag or via the workflow dispatcher whenever you need new binaries.

### Build from source

If you prefer to build locally (or hack on the binding), enable the `python` feature and let [`maturin`](https://github.com/PyO3/maturin) compile the extension:

```bash
uv run maturin develop -F python
```

This installs the extension module in editable mode so that `import tl` picks up local changes.

## Quickstart

```python
import tl

dom = tl.parse('<p id="text">Hello</p>')
text = dom.get_element_by_id("text")
assert text.inner_text() == "Hello"
```

### Finding a tag using the query selector API

```python
import tl

dom = tl.parse('<div><img src="cool-image.png" /></div>')
matches = dom.query_selector('img[src]')

if matches:
    img = matches[0]
    print("Found:", img.outer_html())
else:
    print("No matching tag")
```

### Iterating over the subnodes of an HTML document

```python
import tl

dom = tl.parse('<div><img src="cool-image.png" /></div>')

for node in dom.children():
    name = node.name().unwrap_or("(text)")
    print(f"child={name} inner_text={node.inner_text()}")
```

### Working with classes, attributes, and text

```python
import tl

html = '<div class="a"><p class="a b" id="text">Hello</p></div>'
dom = tl.parse(html)

print([el.inner_text() for el in dom.get_elements_by_class_name("a")])
# ['Hello', 'Hello']

p = dom.get_element_by_id("text")
print(p.get_attribute("class"))
# 'a b'
```

> Note: the binding currently exposes read-only DOM access (querying, traversing, serialization). Mutation APIs from the original crate (e.g., changing attributes) are not yet wrapped, but the underlying Rust code supports them if/when we extend the Python surface.

## License

MIT, inherited from the upstream projects. See `LICENSE` for details.
