# `tl-parser`

[![CI](https://github.com/mgaitan/tl-parser/actions/workflows/test.yml/badge.svg)](https://github.com/mgaitan/tl-parser/actions/workflows/test.yml)
[![pypi version](https://img.shields.io/pypi/v/tl-parser.svg)](https://pypi.org/project/tl-parser/)
[![Changelog](https://img.shields.io/github/v/release/mgaitan/tl-parser?include_prereleases&label=changelog)](https://github.com/mgaitan/tl-parser/releases)

`tl` (installed as `tl-parser`) is a fast HTML parser for Python written in
Rust.

It's a python binding library for
[`astral-tl`](https://github.com/astral-sh/astral-tl)—a maintained fork of the
original [`y21/tl`](https://github.com/y21/tl)—focused on performance, HTML
selector coverage and a stable API.

## Installation

Wheels for Python 3.12–3.14 are published to PyPI. Install with:

```bash
uv add tl-parser
```

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

> Note: the binding currently exposes read-only DOM access (querying,
> traversing, serialization). Mutation APIs from the original crate (e.g.,
> changing attributes) are not yet wrapped, but the underlying Rust code
> supports them if/when we extend the Python surface.

## Benchmarks

In our benchmarks, `tl-parser` parses HTML around 5x faster than the
next-fastest parser and is often 10x-100x faster for class, ID, and CSS lookups.
The chart shows median startup-adjusted time per operation, so lower bars are
better. See the
[benchmark code](https://github.com/mgaitan/tl-parser/blob/main/benches/benchmark.py)
for the workloads and reproduction instructions.

![Python HTML parser benchmark](https://raw.githubusercontent.com/mgaitan/tl-parser/main/benches/results.png)

## Contributing

To hack on the binding, let [`maturin`](https://github.com/PyO3/maturin) compile
the extension from source:

```bash
uv run maturin develop
```

This installs the extension module in editable mode so that `import tl` picks up
local changes. For more background on the project and Python+Rust packaging, see
my blog post
"[Expanding the Python universe with Rust](https://mgaitan.github.io/en/posts/expanding-the-python-universe-with-rust/)".

## License

MIT, inherited from the upstream projects. See `LICENSE` for details.
