//! Python bindings for the HTML parser.
//!
//! Enable the `python` feature and build with `maturin` to produce the
//! `tl` extension module (paquete Python `tl-parser`, import `tl`).

use std::collections::HashMap;
use std::sync::Arc;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::parser::HTMLVersion;
use crate::parser::NodeHandle;
use crate::{parse_owned, Node, ParseError, ParserOptions, VDomGuard};

/// Parses HTML into a DOM that can be used from Python.
#[pyfunction]
pub(crate) fn parse(html: &str) -> PyResult<PyDom> {
    let guard = unsafe {
        parse_owned(
            html.to_owned(),
            ParserOptions::default().track_ids().track_classes(),
        )
    }
    .map_err(to_py_err)?;

    Ok(PyDom {
        dom: Arc::new(guard),
    })
}

/// Python-visible DOM wrapper.
#[derive(Clone)]
#[pyclass(module = "tl", name = "DOM")]
pub(crate) struct PyDom {
    dom: Arc<VDomGuard>,
}

#[pymethods]
impl PyDom {
    /// Returns the element with the provided `id` or `None` if it was not found.
    fn get_element_by_id(&self, id: &str) -> Option<PyElement> {
        self.dom
            .get_ref()
            .get_element_by_id(id)
            .map(|handle| PyElement::new(&self.dom, handle))
    }

    /// Returns all elements that contain the provided class name.
    fn get_elements_by_class_name(&self, class_name: &str) -> Vec<PyElement> {
        self.dom
            .get_ref()
            .get_elements_by_class_name(class_name)
            .map(|handle| PyElement::new(&self.dom, handle))
            .collect()
    }

    /// Returns the top-level children of this DOM (document root nodes).
    fn children(&self) -> Vec<PyElement> {
        self.dom
            .get_ref()
            .children()
            .iter()
            .map(|handle| PyElement::new(&self.dom, *handle))
            .collect()
    }

    /// Returns all elements that match a CSS selector.
    fn query_selector(&self, selector: &str) -> PyResult<Vec<PyElement>> {
        let iter = self
            .dom
            .get_ref()
            .query_selector(selector)
            .ok_or_else(|| PyValueError::new_err("Invalid selector"))?;

        let mut elements = Vec::new();
        for handle in iter {
            elements.push(PyElement::new(&self.dom, handle));
        }

        Ok(elements)
    }

    /// Serializes the entire DOM back into HTML.
    fn outer_html(&self) -> String {
        self.dom.get_ref().outer_html()
    }

    /// Returns the detected HTML version, if any.
    fn version(&self) -> Option<&'static str> {
        self.dom.get_ref().version().map(html_version_to_str)
    }

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!("<DOM nodes={}>", self.dom.get_ref().nodes().len()))
    }
}

/// Python-visible element wrapper.
#[derive(Clone)]
#[pyclass(module = "tl", name = "Element")]
pub(crate) struct PyElement {
    dom: Arc<VDomGuard>,
    handle: NodeHandle,
}

#[pymethods]
impl PyElement {
    /// Returns the concatenated text content of this element.
    fn inner_text(&self) -> PyResult<String> {
        self.render(NodeTextKind::InnerText)
    }

    /// Returns the HTML contained inside this element.
    fn inner_html(&self) -> PyResult<String> {
        self.render(NodeTextKind::InnerHtml)
    }

    /// Returns the element's HTML including the tag itself.
    fn outer_html(&self) -> PyResult<String> {
        self.render(NodeTextKind::OuterHtml)
    }

    /// Returns the element name (tag) if this handle refers to a tag; otherwise `None`.
    fn name(&self) -> PyResult<Option<String>> {
        let dom = self.dom.get_ref();
        let parser = dom.parser();
        let node = self.handle.get(parser).ok_or_else(|| {
            PyValueError::new_err("Node handle is no longer valid for this document")
        })?;

        Ok(node
            .as_tag()
            .map(|tag| tag.name().as_utf8_str().into_owned()))
    }

    /// Returns the value of a given attribute, or `None` if missing.
    fn get_attribute(&self, name: &str) -> PyResult<Option<String>> {
        let dom = self.dom.get_ref();
        let parser = dom.parser();
        let node = self.handle.get(parser).ok_or_else(|| {
            PyValueError::new_err("Node handle is no longer valid for this document")
        })?;

        let Some(tag) = node.as_tag() else {
            return Ok(None);
        };

        Ok(tag
            .attributes()
            .get(name)
            .flatten()
            .map(|v| v.as_utf8_str().into_owned()))
    }

    /// Returns all attributes as a dictionary keyed by attribute name.
    fn attributes(&self) -> PyResult<HashMap<String, Option<String>>> {
        let dom = self.dom.get_ref();
        let parser = dom.parser();
        let node = self.handle.get(parser).ok_or_else(|| {
            PyValueError::new_err("Node handle is no longer valid for this document")
        })?;

        let Some(tag) = node.as_tag() else {
            return Ok(HashMap::new());
        };

        Ok(tag
            .attributes()
            .iter()
            .map(|(k, v)| (k.into_owned(), v.map(|value| value.into_owned())))
            .collect())
    }

    /// Returns the `id` attribute if present.
    fn id(&self) -> PyResult<Option<String>> {
        self.get_attribute("id")
    }

    /// Returns the raw `class` attribute value if present.
    fn class_name(&self) -> PyResult<Option<String>> {
        self.get_attribute("class")
    }

    /// Returns the class list as a list of individual tokens.
    fn class_list(&self) -> PyResult<Vec<String>> {
        Ok(self
            .class_name()?
            .map(|value| value.split_whitespace().map(str::to_owned).collect())
            .unwrap_or_default())
    }

    /// Checks if the element has the provided class name.
    fn has_class(&self, name: &str) -> PyResult<bool> {
        let dom = self.dom.get_ref();
        let parser = dom.parser();
        let node = self.handle.get(parser).ok_or_else(|| {
            PyValueError::new_err("Node handle is no longer valid for this document")
        })?;

        let Some(tag) = node.as_tag() else {
            return Ok(false);
        };

        Ok(tag.attributes().is_class_member(name))
    }

    /// Returns the direct children of this element (raw nodes included).
    fn children(&self) -> PyResult<Vec<PyElement>> {
        let dom = self.dom.get_ref();
        let parser = dom.parser();
        let node = self.handle.get(parser).ok_or_else(|| {
            PyValueError::new_err("Node handle is no longer valid for this document")
        })?;

        let Some(children) = node.children() else {
            return Ok(Vec::new());
        };

        Ok(children
            .top()
            .iter()
            .map(|handle| PyElement::new(&self.dom, *handle))
            .collect())
    }

    /// Returns the node type (`element`, `text`, or `comment`).
    fn node_type(&self) -> PyResult<&'static str> {
        let dom = self.dom.get_ref();
        let parser = dom.parser();
        let node = self.handle.get(parser).ok_or_else(|| {
            PyValueError::new_err("Node handle is no longer valid for this document")
        })?;

        let kind = match node {
            Node::Tag(_) => "element",
            Node::Raw(_) => "text",
            Node::Comment(_) => "comment",
        };

        Ok(kind)
    }

    /// Returns all elements under this node that match a CSS selector.
    fn query_selector(&self, selector: &str) -> PyResult<Vec<PyElement>> {
        let dom = self.dom.get_ref();
        let parser = dom.parser();
        let node = self.handle.get(parser).ok_or_else(|| {
            PyValueError::new_err("Node handle is no longer valid for this document")
        })?;

        let tag = node
            .as_tag()
            .ok_or_else(|| PyValueError::new_err("This node is not an element"))?;

        let iter = tag
            .query_selector(parser, selector)
            .ok_or_else(|| PyValueError::new_err("Invalid selector"))?;

        let mut elements = Vec::new();
        for handle in iter {
            elements.push(PyElement::new(&self.dom, handle));
        }

        Ok(elements)
    }

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!("<Element id={}>", self.handle.get_inner()))
    }
}

impl PyElement {
    fn new(dom: &Arc<VDomGuard>, handle: NodeHandle) -> Self {
        Self {
            dom: Arc::clone(dom),
            handle,
        }
    }

    fn render(&self, kind: NodeTextKind) -> PyResult<String> {
        let dom = self.dom.get_ref();
        let parser = dom.parser();
        let node = self.handle.get(parser).ok_or_else(|| {
            PyValueError::new_err("Node handle is no longer valid for this document")
        })?;

        let content = match kind {
            NodeTextKind::InnerText => node.inner_text(parser),
            NodeTextKind::InnerHtml => node.inner_html(parser),
            NodeTextKind::OuterHtml => node.outer_html(parser),
        };

        Ok(content.into_owned())
    }
}

enum NodeTextKind {
    InnerText,
    InnerHtml,
    OuterHtml,
}

fn to_py_err(err: ParseError) -> PyErr {
    PyValueError::new_err(err.to_string())
}

fn html_version_to_str(version: HTMLVersion) -> &'static str {
    match version {
        HTMLVersion::HTML5 => "html5",
        HTMLVersion::StrictHTML401 => "html4-strict",
        HTMLVersion::TransitionalHTML401 => "html4-transitional",
        HTMLVersion::FramesetHTML401 => "html4-frameset",
    }
}

/// Creates the `tl` Python extension module.
#[pymodule]
pub(crate) fn tl(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse, m)?)?;
    m.add_class::<PyDom>()?;
    m.add_class::<PyElement>()?;

    Ok(())
}
