#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include "doc2struct.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <limits.h>

static int native_error(Arena *a) {
    if (!a->error[0])
        return 0;
    if (!strcmp(a->error, "out of memory"))
        PyErr_NoMemory();
    else
        PyErr_SetString(PyExc_ValueError, a->error);
    return 1;
}
static Str string(Arena *a, PyObject *o) {
    Py_ssize_t n;
    const char *p;
    if (!o || o == Py_None)
        return (Str){0};
    if (!PyUnicode_Check(o)) {
        PyErr_SetString(PyExc_TypeError, "expected a string");
        return (Str){0};
    }
    p = PyUnicode_AsUTF8AndSize(o, &n);
    if (!p)
        return (Str){0};
    return ds_copy(a, (Str){p, (size_t)n});
}
static PyObject *unicode(Str s) {
    if (!s.p)
        return Py_NewRef(Py_None);
    if (s.n > PY_SSIZE_T_MAX) {
        PyErr_NoMemory();
        return NULL;
    }
    return PyUnicode_DecodeUTF8(s.p, (Py_ssize_t)s.n, "strict");
}
static PyObject *get(PyObject *d, const char *key) {
    PyObject *o;
    if (!PyDict_Check(d)) {
        PyErr_SetString(PyExc_TypeError, "expected a dictionary");
        return NULL;
    }
    o = PyDict_GetItemString(d, key);
    if (!o)
        PyErr_Format(PyExc_KeyError, "missing field: %s", key);
    return o;
}
static long integer(PyObject *d, const char *key) {
    PyObject *o = get(d, key);
    return o ? PyLong_AsLong(o) : -1;
}
static int boolean(PyObject *d, const char *key) {
    PyObject *o = get(d, key);
    return o ? PyObject_IsTrue(o) : -1;
}
static int set(PyObject *d, const char *key, PyObject *value) {
    int rc;
    if (!value)
        return 0;
    rc = PyDict_SetItemString(d, key, value);
    Py_DECREF(value);
    return rc == 0;
}
static int setstr(PyObject *d, const char *key, Str s) { return set(d, key, unicode(s)); }
static void capsule_free(PyObject *c) {
    Rules *r = PyCapsule_GetPointer(c, "doc2struct.Rules");
    if (r) {
        ds_rules_free(r);
        free(r);
    } else
        PyErr_Clear();
}
static PyObject *prepare_rules(PyObject *self, PyObject *config) {
    Rules *r = calloc(1, sizeof(*r));
    PyObject *o, *seq = NULL, *sub, *value;
    Py_ssize_t i, j, n;
    if (!r)
        return PyErr_NoMemory();
    o = get(config, "headers");
    if (!o)
        goto error;
    seq = PySequence_Fast(o, "headers must be a sequence");
    if (!seq)
        goto error;
    n = PySequence_Fast_GET_SIZE(seq);
    r->headers = ds_alloc(&r->arena, (size_t)n * sizeof(Header));
    if (!r->headers)
        goto error;
    r->nheaders = (size_t)n;
    for (i = 0; i < n; i++) {
        Header *h = r->headers + i;
        PyObject *requires;
        sub = PySequence_Fast_GET_ITEM(seq, i);
        h->name = string(&r->arena, get(sub, "name"));
        {
            long level = integer(sub, "level");
            if (PyErr_Occurred())
                goto error;
            if (level < INT_MIN || level >= INT_MAX) {
                PyErr_SetString(PyExc_ValueError,
                                "header level is outside the native integer range");
                goto error;
            }
            h->level = (int)level;
        }
        h->rx = ds_regex(r, string(&r->arena, get(sub, "regex")), 0);
        if (PyErr_Occurred() || !h->rx)
            goto error;
        value = PyDict_GetItemString(sub, "requires");
        if (!value)
            continue;
        requires = PySequence_Fast(value, "requires must be a sequence");
        if (!requires)
            goto error;
        for (j = 0; j < PySequence_Fast_GET_SIZE(requires); j++) {
            unsigned bit = ds_style_bit(string(&r->arena, PySequence_Fast_GET_ITEM(requires, j)));
            if (!bit) {
                Py_DECREF(requires);
                PyErr_SetString(PyExc_ValueError, "unknown required header style");
                goto error;
            }
            h->requires |= bit;
        }
        Py_DECREF(requires);
    }
    Py_CLEAR(seq);
    sub = get(config, "remove");
    if (!sub)
        goto error;
    value = get(sub, "repeat_threshold");
    if (!value)
        goto error;
    r->repeat_threshold = value == Py_None ? 0 : PyLong_AsLong(value);
    o = get(sub, "patterns");
    if (!o)
        goto error;
    seq = PySequence_Fast(o, "patterns must be a sequence");
    if (!seq)
        goto error;
    n = PySequence_Fast_GET_SIZE(seq);
    r->remove = ds_alloc(&r->arena, (size_t)n * sizeof(Remove));
    if (!r->remove)
        goto error;
    r->nremove = (size_t)n;
    for (i = 0; i < n; i++) {
        PyObject *pair =
            PySequence_Fast(PySequence_Fast_GET_ITEM(seq, i), "remove pattern must be a pair");
        if (!pair)
            goto error;
        if (PySequence_Fast_GET_SIZE(pair) != 2) {
            Py_DECREF(pair);
            PyErr_SetString(PyExc_ValueError, "remove pattern must be a pair");
            goto error;
        }
        r->remove[i].rx = ds_regex(r, string(&r->arena, PySequence_Fast_GET_ITEM(pair, 0)), 0);
        r->remove[i].needs_href = PyObject_IsTrue(PySequence_Fast_GET_ITEM(pair, 1));
        Py_DECREF(pair);
        if (!r->remove[i].rx || PyErr_Occurred())
            goto error;
    }
    Py_CLEAR(seq);
    sub = get(config, "tables");
    if (!sub)
        goto error;
    r->single_row_to_text = boolean(sub, "single_row_to_text");
    r->title_from_section = boolean(sub, "title_from_section");
    r->footnote_lines = integer(sub, "footnote_lines");
    r->preamble_lines = integer(sub, "preamble_lines");
    r->postamble_lines = integer(sub, "postamble_lines");
    value = get(sub, "footnote_regex");
    if (!value)
        goto error;
    if (value != Py_None && PyObject_IsTrue(value)) {
        r->footnote = ds_regex(r, string(&r->arena, value), 0);
        if (!r->footnote)
            goto error;
    }
    o = get(sub, "steps");
    if (!o)
        goto error;
    seq = PySequence_Fast(o, "table steps must be a sequence");
    if (!seq)
        goto error;
    for (i = 0; i < PySequence_Fast_GET_SIZE(seq); i++) {
        Str step = string(&r->arena, PySequence_Fast_GET_ITEM(seq, i));
        for (j = 0; ds_table_steps[j]; j++)
            if (ds_is(step, ds_table_steps[j]))
                break;
        if (!ds_table_steps[j]) {
            PyErr_SetString(PyExc_ValueError, "unknown table step");
            goto error;
        }
        r->table_steps |= 1u << j;
    }
    Py_CLEAR(seq);
    o = get(config, "columns");
    if (!o)
        goto error;
    seq = PySequence_Fast(o, "columns must be a sequence");
    if (!seq)
        goto error;
    n = PySequence_Fast_GET_SIZE(seq);
    r->columns = ds_alloc(&r->arena, (size_t)n * sizeof(Column));
    if (!r->columns)
        goto error;
    r->ncolumns = (size_t)n;
    for (i = 0; i < n; i++) {
        Column *c = r->columns + i;
        sub = PySequence_Fast_GET_ITEM(seq, i);
        c->name = string(&r->arena, get(sub, "name"));
        c->source = string(&r->arena, get(sub, "source"));
        c->dtype = string(&r->arena, get(sub, "dtype"));
        c->which = string(&r->arena, get(sub, "which"));
        value = PyDict_GetItemString(sub, "pattern");
        if (value && value != Py_None && PyObject_IsTrue(value)) {
            c->rx = ds_regex(r, string(&r->arena, value), 1);
            if (!c->rx)
                goto error;
        }
        value = PyDict_GetItemString(sub, "types");
        if (value && value != Py_None) {
            PyObject *types = PySequence_Fast(value, "column types must be a sequence");
            if (!types)
                goto error;
            c->ntypes = (size_t)PySequence_Fast_GET_SIZE(types);
            c->filter_types = c->ntypes != 0;
            c->types = ds_alloc(&r->arena, c->ntypes * sizeof(Str));
            if (!c->types) {
                Py_DECREF(types);
                goto error;
            }
            for (j = 0; j < (Py_ssize_t)c->ntypes; j++)
                c->types[j] = string(&r->arena, PySequence_Fast_GET_ITEM(types, j));
            Py_DECREF(types);
        }
    }
    Py_CLEAR(seq);
    if (PyErr_Occurred() || native_error(&r->arena))
        goto error;
    {
        PyObject *capsule = PyCapsule_New(r, "doc2struct.Rules", capsule_free);
        if (!capsule)
            goto error;
        return capsule;
    }
error:
    Py_XDECREF(seq);
    if (!PyErr_Occurred())
        native_error(&r->arena);
    if (!PyErr_Occurred())
        PyErr_SetString(PyExc_ValueError, "invalid native rules");
    ds_rules_free(r);
    free(r);
    return NULL;
}
static int input(PyObject *o, Str *out, PyObject **owner) {
    Py_ssize_t n;
    const char *p;
    *owner = NULL;
    if (PyUnicode_Check(o)) {
        p = PyUnicode_AsUTF8AndSize(o, &n);
        if (!p)
            return 0;
        *out = (Str){p, (size_t)n};
        return 1;
    }
    if (PyByteArray_Check(o)) {
        *owner = PyBytes_FromObject(o);
        if (!*owner)
            return 0;
        o = *owner;
    }
    if (!PyBytes_Check(o)) {
        PyErr_SetString(PyExc_TypeError, "html must be bytes, bytearray, or str");
        return 0;
    }
    *out = (Str){PyBytes_AS_STRING(o), (size_t)PyBytes_GET_SIZE(o)};
    return 1;
}
static int token_sink(void *ctx, int kind, Str value, const Attrs *a) {
    Document *d = ctx;
    Token *t = ds_push(&d->arena, &d->tokens, sizeof(Token));
    if (!t)
        return 0;
    t->kind = kind;
    t->value = value;
    if (a)
        t->attrs = *a;
    return 1;
}
static PyObject *export_tokens(Document *d) {
    static const char *names[] = {"style", "colspan", "rowspan", "href", "src", "alt", "hidden"};
    PyObject *list = PyList_New((Py_ssize_t)d->tokens.n);
    size_t i, j;
    if (!list)
        return NULL;
    for (i = 0; i < d->tokens.n; i++) {
        Token *t = (Token *)d->tokens.p + i;
        PyObject *attrs = Py_NewRef(Py_None), *tuple, *text = unicode(t->value);
        if (!text)
            goto error;
        if (t->kind == START) {
            Py_SETREF(attrs, PyDict_New());
            if (!attrs) {
                Py_DECREF(text);
                goto error;
            }
            for (j = 0; j < A_COUNT; j++)
                if (t->attrs.value[j].p && !setstr(attrs, names[j], t->attrs.value[j])) {
                    Py_DECREF(text);
                    Py_DECREF(attrs);
                    goto error;
                }
        }
        tuple = Py_BuildValue("iNN", t->kind, text, attrs);
        if (!tuple)
            goto error;
        PyList_SET_ITEM(list, (Py_ssize_t)i, tuple);
    }
    return list;
error:
    Py_DECREF(list);
    return NULL;
}
static PyObject *tokenize(PyObject *self, PyObject *html) {
    Document d = {0};
    Str text;
    PyObject *owner = NULL, *result = NULL;
    int ok;
    if (!input(html, &text, &owner))
        goto done;
    Py_BEGIN_ALLOW_THREADS text = ds_input(&d.arena, text);
    ok = text.p && ds_tokenize(&d, text, token_sink, &d);
    Py_END_ALLOW_THREADS if (!ok) {
        native_error(&d.arena);
        goto done;
    }
    result = export_tokens(&d);
done:
    ds_document_free(&d);
    Py_XDECREF(owner);
    return result;
}
static PyObject *export_runs(Document *d) {
    PyObject *list = PyList_New((Py_ssize_t)d->runs.n);
    size_t i;
    if (!list)
        return NULL;
    for (i = 0; i < d->runs.n; i++) {
        Run *r = (Run *)d->runs.p + i;
        PyObject *row = PyDict_New();
        if (!row)
            goto error;
        if (!set(row, "block", PyLong_FromSize_t(r->block)) ||
            !set(row, "line", PyLong_FromSize_t(r->line)) ||
            !set(row, "row", r->in_table ? PyLong_FromSize_t(r->row) : Py_NewRef(Py_None)) ||
            !set(row, "col", r->in_table ? PyLong_FromSize_t(r->col) : Py_NewRef(Py_None)) ||
            !set(row, "span",
                 r->rowspan > 1 || r->colspan > 1
                     ? PyUnicode_FromFormat("%zux%zu", r->rowspan, r->colspan)
                     : Py_NewRef(Py_None)) ||
            !setstr(row, "text", r->text) ||
            !set(row, "flags", PyLong_FromUnsignedLong(r->flags)) ||
            !set(row, "font_size", r->has_font ? PyLong_FromDouble(r->font) : Py_NewRef(Py_None)) ||
            !set(row, "indent",
                 r->has_indent ? PyLong_FromDouble(r->indent) : Py_NewRef(Py_None)) ||
            !setstr(row, "href", r->href) || !setstr(row, "tag", r->tag) ||
            !setstr(row, "src", r->src)) {
            Py_DECREF(row);
            goto error;
        }
        PyList_SET_ITEM(list, (Py_ssize_t)i, row);
    }
    return list;
error:
    Py_DECREF(list);
    return NULL;
}
static int import_tokens(Document *d, PyObject *tokens) {
    PyObject *it = PyObject_GetIter(tokens), *o;
    if (!it)
        return 0;
    while ((o = PyIter_Next(it))) {
        PyObject *t = PySequence_Fast(o, "token must be a triple");
        Token *dst;
        size_t j;
        static const char *names[] = {"style", "colspan", "rowspan", "href",
                                      "src",   "alt",     "hidden"};
        Py_DECREF(o);
        if (!t)
            goto error;
        if (PySequence_Fast_GET_SIZE(t) != 3) {
            Py_DECREF(t);
            PyErr_SetString(PyExc_ValueError, "token must contain three values");
            goto error;
        }
        dst = ds_push(&d->arena, &d->tokens, sizeof(Token));
        if (!dst) {
            Py_DECREF(t);
            native_error(&d->arena);
            goto error;
        }
        dst->kind = (int)PyLong_AsLong(PySequence_Fast_GET_ITEM(t, 0));
        dst->value = string(&d->arena, PySequence_Fast_GET_ITEM(t, 1));
        if (dst->kind == START) {
            PyObject *attrs = PySequence_Fast_GET_ITEM(t, 2);
            if (!PyDict_Check(attrs)) {
                Py_DECREF(t);
                PyErr_SetString(PyExc_TypeError, "start token attributes must be a dict");
                goto error;
            }
            for (j = 0; j < A_COUNT; j++) {
                PyObject *v = PyDict_GetItemString(attrs, names[j]);
                if (v)
                    dst->attrs.value[j] = string(&d->arena, v);
            }
        }
        Py_DECREF(t);
        if (PyErr_Occurred())
            goto error;
    }
    Py_DECREF(it);
    return !PyErr_Occurred() && !native_error(&d->arena);
error:
    Py_DECREF(it);
    return 0;
}
static PyObject *normalize(PyObject *self, PyObject *args) {
    PyObject *tokens, *result = NULL;
    Document d = {0};
    Options options = {0, 0, 100};
    Py_ssize_t cap = 100;
    int ok = 0;
    void *n;
    if (!PyArg_ParseTuple(args, "O|ppn:normalize", &tokens, &options.hide_hidden_attr,
                          &options.hide_visibility, &cap))
        return NULL;
    if (cap < 1) {
        PyErr_SetString(PyExc_ValueError, "max_span must be positive");
        return NULL;
    }
    options.max_span = (size_t)cap;
    if (!import_tokens(&d, tokens))
        goto done;
    Py_BEGIN_ALLOW_THREADS n = ds_normalizer(&d, options);
    if (n) {
        size_t i;
        ok = 1;
        for (i = 0; i < d.tokens.n; i++) {
            Token *t = (Token *)d.tokens.p + i;
            if (!ds_normalize_token(n, t->kind, t->value, &t->attrs)) {
                ok = 0;
                break;
            }
        }
        if (ok)
            ok = ds_normalize_finish(n);
    }
    Py_END_ALLOW_THREADS if (ok) result = export_runs(&d);
    else native_error(&d.arena);
done:
    ds_document_free(&d);
    return result;
}
static int import_runs(Document *d, PyObject *instructions) {
    PyObject *seq = PySequence_Fast(instructions, "instructions must be a sequence");
    Py_ssize_t i;
    if (!seq)
        return 0;
    for (i = 0; i < PySequence_Fast_GET_SIZE(seq); i++) {
        PyObject *o = PySequence_Fast_GET_ITEM(seq, i), *v;
        Run *r = ds_push(&d->arena, &d->runs, sizeof(Run));
        if (!r)
            goto error;
        r->rowspan = r->colspan = 1;
#define SIZE_FIELD(name)                                                                           \
    v = get(o, #name);                                                                             \
    if (!v)                                                                                        \
        goto error;                                                                                \
    r->name = PyLong_AsSize_t(v)
        SIZE_FIELD(block);
        SIZE_FIELD(line);
        v = get(o, "row");
        if (!v)
            goto error;
        if (v != Py_None) {
            r->in_table = 1;
            r->row = PyLong_AsSize_t(v);
            SIZE_FIELD(col);
        }
#undef SIZE_FIELD
        r->text = string(&d->arena, get(o, "text"));
        if (!r->text.p && !PyErr_Occurred())
            r->text = ds_str("");
        r->href = string(&d->arena, get(o, "href"));
        r->src = string(&d->arena, get(o, "src"));
        v = PyDict_GetItemString(o, "tag");
        if (v)
            r->tag = string(&d->arena, v);
        v = get(o, "flags");
        if (!v)
            goto error;
        r->flags = v == Py_None ? 0 : (unsigned)PyLong_AsUnsignedLong(v);
        v = get(o, "font_size");
        if (!v)
            goto error;
        if (v != Py_None) {
            r->has_font = 1;
            r->font = PyFloat_AsDouble(v);
            r->font_float = PyFloat_Check(v);
        }
        v = get(o, "indent");
        if (!v)
            goto error;
        if (v != Py_None) {
            r->has_indent = 1;
            r->indent = PyFloat_AsDouble(v);
            r->indent_float = PyFloat_Check(v);
        }
        v = get(o, "span");
        if (!v)
            goto error;
        if (v != Py_None && PyObject_IsTrue(v)) {
            Str span = string(&d->arena, v);
            char *end;
            unsigned long long rs, cs = 0;
            if (!span.p)
                goto error;
            rs = strtoull(span.p, &end, 10);
            if (end && *end == 'x')
                cs = strtoull(end + 1, &end, 10);
            if (!rs || !cs || *end || rs > SIZE_MAX || cs > SIZE_MAX) {
                PyErr_SetString(PyExc_ValueError, "invalid instruction span");
                goto error;
            }
            r->rowspan = (size_t)rs;
            r->colspan = (size_t)cs;
        }
        if (PyErr_Occurred())
            goto error;
    }
    Py_DECREF(seq);
    return !native_error(&d->arena);
error:
    Py_DECREF(seq);
    if (!PyErr_Occurred())
        native_error(&d->arena);
    return 0;
}
static PyObject *matrix(Matrix *m) {
    PyObject *rows = PyList_New((Py_ssize_t)m->nr);
    size_t i, j;
    if (!rows)
        return NULL;
    for (i = 0; i < m->nr; i++) {
        PyObject *row = PyList_New((Py_ssize_t)m->nc);
        if (!row) {
            Py_DECREF(rows);
            return NULL;
        }
        PyList_SET_ITEM(rows, (Py_ssize_t)i, row);
        for (j = 0; j < m->nc; j++) {
            PyObject *v = unicode(m->cells[i * m->nc + j]);
            if (!v) {
                Py_DECREF(rows);
                return NULL;
            }
            PyList_SET_ITEM(row, (Py_ssize_t)j, v);
        }
    }
    return rows;
}
static PyObject *notes(Row *r) {
    PyObject *list;
    size_t i;
    if (!r->nnotes)
        return Py_NewRef(Py_None);
    list = PyList_New((Py_ssize_t)r->nnotes);
    if (!list)
        return NULL;
    for (i = 0; i < r->nnotes; i++) {
        PyObject *pair = PyList_New(2), *id, *text;
        if (!pair) {
            Py_DECREF(list);
            return NULL;
        }
        PyList_SET_ITEM(list, (Py_ssize_t)i, pair);
        id = unicode(r->notes[i].id);
        if (!id) {
            Py_DECREF(list);
            return NULL;
        }
        PyList_SET_ITEM(pair, 0, id);
        text = unicode(r->notes[i].text);
        if (!text) {
            Py_DECREF(list);
            return NULL;
        }
        PyList_SET_ITEM(pair, 1, text);
    }
    return list;
}
static PyObject *cast(PyObject *value, Str dtype) {
    PyObject *out;
    if (!value || value == Py_None)
        return value;
    if (ds_is(dtype, "int"))
        out = PyUnicode_Check(value) ? PyLong_FromUnicodeObject(value, 10) : PyNumber_Long(value);
    else if (ds_is(dtype, "bool")) {
        int truth = PyObject_IsTrue(value);
        out = truth < 0 ? NULL : PyBool_FromLong(truth);
    } else
        out = PyObject_Str(value);
    Py_DECREF(value);
    if (!out &&
        (PyErr_ExceptionMatches(PyExc_ValueError) || PyErr_ExceptionMatches(PyExc_TypeError))) {
        PyErr_Clear();
        return Py_NewRef(Py_None);
    }
    return out;
}
static PyObject *source(Item *it, Str name) {
    Run *r = &it->run;
    if (ds_is(name, "href"))
        return unicode(r->href);
    if (ds_is(name, "src"))
        return unicode(r->src);
    if (ds_is(name, "font_size"))
        return r->has_font
                   ? (r->font_float ? PyFloat_FromDouble(r->font) : PyLong_FromDouble(r->font))
                   : Py_NewRef(Py_None);
    if (ds_is(name, "indent"))
        return r->has_indent ? (r->indent_float ? PyFloat_FromDouble(r->indent)
                                                : PyLong_FromDouble(r->indent))
                             : Py_NewRef(Py_None);
    if (ds_is(name, "flags"))
        return PyLong_FromUnsignedLong(r->flags);
    return Py_NewRef(Py_None);
}
static PyObject *custom(Document *d, Column *c, Row *r) {
    size_t i;
    int all = ds_is(c->which, "all") || ds_is(c->dtype, "list");
    PyObject *values;
    if (ds_is(r->type, "table"))
        return Py_NewRef(Py_None);
    if (c->filter_types) {
        for (i = 0; i < c->ntypes; i++)
            if (ds_eq(r->type, c->types[i]))
                break;
        if (i == c->ntypes)
            return Py_NewRef(Py_None);
    }
    if (ds_is(c->source, "text")) {
        Str text = r->text;
        if (c->rx) {
            if (ds_match(d, c->rx, text, 1))
                text = ds_group(d, text, c->rx->groups ? 1 : 0);
            else
                text = (Str){0};
            if (native_error(&d->arena))
                return NULL;
        }
        return cast(unicode(text), c->dtype);
    }
    values = PyList_New(0);
    if (!values)
        return NULL;
    for (i = 0; i < r->nitems; i++) {
        PyObject *v = source(r->items + i, c->source), *converted;
        if (!v)
            goto error;
        if (v == Py_None) {
            Py_DECREF(v);
            continue;
        }
        converted = cast(v, ds_is(c->dtype, "list") ? ds_str("str") : c->dtype);
        if (!converted)
            goto error;
        if (PyList_Append(values, converted) < 0) {
            Py_DECREF(converted);
            goto error;
        }
        Py_DECREF(converted);
    }
    if (all)
        return values;
    {
        Py_ssize_t n = PyList_GET_SIZE(values);
        PyObject *result =
            n ? Py_NewRef(PyList_GET_ITEM(values, ds_is(c->which, "first") ? 0 : n - 1))
              : Py_NewRef(Py_None);
        Py_DECREF(values);
        return result;
    }
error:
    Py_DECREF(values);
    return NULL;
}
static PyObject *export_rows(Document *d, Rules *r, int with_rules) {
    PyObject *list = PyList_New((Py_ssize_t)d->rows.n);
    size_t i, j;
    if (!list)
        return NULL;
    for (i = 0; i < d->rows.n; i++) {
        Row *row = (Row *)d->rows.p + i;
        PyObject *out = PyDict_New();
        if (!out)
            goto error;
        if (!set(out, "id", PyLong_FromSize_t(row->id)) ||
            !set(out, "level", PyLong_FromSize_t(row->level)) || !setstr(out, "type", row->type) ||
            (with_rules && (!setstr(out, "class", row->klass) ||
                            !setstr(out, "standardized_title", row->title))) ||
            !setstr(out, "text", row->text) ||
            !set(out, "matrix", row->matrix.nr ? matrix(&row->matrix) : Py_NewRef(Py_None)) ||
            !set(out, "cleaned",
                 row->cleaned < 0 ? Py_NewRef(Py_None) : PyBool_FromLong(row->cleaned)) ||
            !setstr(out, "preamble", row->preamble) || !set(out, "footnotes", notes(row)) ||
            !setstr(out, "postamble", row->postamble)) {
            Py_DECREF(out);
            goto error;
        }
        for (j = 0; j < r->ncolumns; j++) {
            PyObject *key = unicode(r->columns[j].name), *value;
            if (!key) {
                Py_DECREF(out);
                goto error;
            }
            value = custom(d, r->columns + j, row);
            if (!value) {
                Py_DECREF(key);
                Py_DECREF(out);
                goto error;
            }
            if (PyDict_SetItem(out, key, value) < 0) {
                Py_DECREF(key);
                Py_DECREF(value);
                Py_DECREF(out);
                goto error;
            }
            Py_DECREF(key);
            Py_DECREF(value);
        }
        PyList_SET_ITEM(list, (Py_ssize_t)i, out);
    }
    return list;
error:
    Py_DECREF(list);
    return NULL;
}
static PyObject *standardize(PyObject *self, PyObject *args) {
    PyObject *instructions, *capsule, *result = NULL;
    Document d = {0};
    Rules *r;
    int with_rules, ok;
    if (!PyArg_ParseTuple(args, "OOp:standardize", &instructions, &capsule, &with_rules))
        return NULL;
    r = PyCapsule_GetPointer(capsule, "doc2struct.Rules");
    if (!r)
        return NULL;
    if (!import_runs(&d, instructions))
        goto done;
    Py_BEGIN_ALLOW_THREADS ok = ds_standardize(&d, r);
    Py_END_ALLOW_THREADS if (ok) result = export_rows(&d, r, with_rules);
    else native_error(&d.arena);
done:
    ds_document_free(&d);
    return result;
}
static PyObject *parse_html(PyObject *self, PyObject *args) {
    PyObject *html, *capsule, *owner = NULL, *result = NULL;
    Rules *r;
    Document d = {0};
    Options options = {0, 0, 100};
    Py_ssize_t cap = 100;
    Str text;
    int with_rules, ok = 0;
    void *n;
    if (!PyArg_ParseTuple(args, "OOp|ppn:parse_html", &html, &capsule, &with_rules,
                          &options.hide_hidden_attr, &options.hide_visibility, &cap))
        return NULL;
    if (cap < 1) {
        PyErr_SetString(PyExc_ValueError, "max_span must be positive");
        return NULL;
    }
    options.max_span = (size_t)cap;
    r = PyCapsule_GetPointer(capsule, "doc2struct.Rules");
    if (!r)
        return NULL;
    if (!input(html, &text, &owner))
        goto done;
    Py_BEGIN_ALLOW_THREADS text = ds_input(&d.arena, text);
    n = ds_normalizer(&d, options);
    if (text.p && n)
        ok = ds_tokenize(&d, text, ds_normalize_token, n) && ds_normalize_finish(n) &&
             ds_standardize(&d, r);
    Py_END_ALLOW_THREADS if (ok) result = export_rows(&d, r, with_rules);
    else native_error(&d.arena);
done:
    ds_document_free(&d);
    Py_XDECREF(owner);
    return result;
}
static PyMethodDef methods[] = {
    {"prepare_rules", prepare_rules, METH_O, "Compile immutable native rules."},
    {"parse_html", parse_html, METH_VARARGS, "Parse HTML with native intermediate storage."},
    {"tokenize", tokenize, METH_O, "Return tokens from the native scanner."},
    {"normalize", normalize, METH_VARARGS, "Normalize a Python token iterable."},
    {"standardize", standardize, METH_VARARGS, "Standardize Python instruction rows."},
    {NULL, NULL, 0, NULL}};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_native", "Native doc2struct engine.",
                                    0, methods};
PyMODINIT_FUNC PyInit__native(void) { return PyModule_Create(&module); }
