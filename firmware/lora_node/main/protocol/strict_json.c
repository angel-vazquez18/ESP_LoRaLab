#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "strict_json.h"

// cJSON reserves its low byte for types and bits 8/9 for ownership flags.
#define INTEGER_TOKEN (1 << 16)

typedef struct {
    const unsigned char *p, *end;
} cursor;

static bool utf8(const unsigned char *p, size_t n)
{
    for (size_t i = 0; i < n;) {
        unsigned c = p[i++], count, minimum;
        uint32_t value;
        if (c == 0)
            return false;
        if (c < 0x80)
            continue;
        if (c >= 0xc2 && c <= 0xdf) {
            count = 1;
            minimum = 0x80;
            value = c & 31;
        } else if (c >= 0xe0 && c <= 0xef) {
            count = 2;
            minimum = 0x800;
            value = c & 15;
        } else if (c >= 0xf0 && c <= 0xf4) {
            count = 3;
            minimum = 0x10000;
            value = c & 7;
        } else
            return false;
        if (i + count > n)
            return false;
        while (count--) {
            c = p[i++];
            if ((c & 0xc0) != 0x80)
                return false;
            value = (value << 6) | (c & 63);
        }
        if (value < minimum || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff))
            return false;
    }
    return true;
}

static void whitespace(cursor *c)
{
    while (c->p < c->end && (*c->p == ' ' || *c->p == '\t' || *c->p == '\r' || *c->p == '\n'))
        c->p++;
}

static bool take(cursor *c, unsigned char ch)
{
    if (c->p == c->end || *c->p != ch)
        return false;
    c->p++;
    return true;
}

static bool hex4(cursor *c, unsigned *out)
{
    if (c->end - c->p < 4)
        return false;
    unsigned value = 0;
    for (unsigned i = 0; i < 4; i++) {
        unsigned ch = *c->p++, digit;
        if (ch >= '0' && ch <= '9')
            digit = ch - '0';
        else if (ch >= 'a' && ch <= 'f')
            digit = ch - 'a' + 10;
        else if (ch >= 'A' && ch <= 'F')
            digit = ch - 'A' + 10;
        else
            return false;
        value = value * 16 + digit;
    }
    *out = value;
    return true;
}

static bool string(cursor *c)
{
    if (!take(c, '"'))
        return false;
    while (c->p < c->end) {
        unsigned ch = *c->p++;
        if (ch == '"')
            return true;
        if (ch < 32)
            return false;
        if (ch != '\\')
            continue;
        if (c->p == c->end)
            return false;
        ch = *c->p++;
        if (strchr("\"\\/bfnrt", ch))
            continue;
        if (ch != 'u')
            return false;
        unsigned value;
        if (!hex4(c, &value) || value == 0)
            return false; // cJSON strings use NUL.
        if (value >= 0xdc00 && value <= 0xdfff)
            return false;
        if (value >= 0xd800 && value <= 0xdbff) {
            if (!take(c, '\\') || !take(c, 'u') || !hex4(c, &value) || value < 0xdc00 ||
                value > 0xdfff)
                return false;
        }
    }
    return false;
}

static bool digit(cursor *c) { return c->p < c->end && *c->p >= '0' && *c->p <= '9'; }

static bool number(cursor *c, cJSON *tree)
{
    bool integer = true;
    (void)take(c, '-');
    if (!take(c, '0')) {
        if (!digit(c) || *c->p == '0')
            return false;
        do {
            c->p++;
        } while (digit(c));
    }
    if (take(c, '.')) {
        integer = false;
        if (!digit(c))
            return false;
        do {
            c->p++;
        } while (digit(c));
    }
    if (take(c, 'e') || take(c, 'E')) {
        integer = false;
        if (!take(c, '+'))
            (void)take(c, '-');
        if (!digit(c))
            return false;
        do {
            c->p++;
        } while (digit(c));
    }
    if (tree && integer)
        tree->type |= INTEGER_TOKEN;
    return true;
}

static bool value(cursor *c, unsigned depth, cJSON *tree)
{
    whitespace(c);
    if (c->p == c->end)
        return false;
    unsigned ch = *c->p;
    if (ch == '{' || ch == '[') {
        if (depth >= 8)
            return false;
        c->p++;
        unsigned close = ch == '{' ? '}' : ']';
        whitespace(c);
        if (take(c, close))
            return true;
        cJSON *child = tree ? tree->child : NULL;
        do {
            whitespace(c);
            if (ch == '{') {
                if (!string(c))
                    return false;
                whitespace(c);
                if (!take(c, ':'))
                    return false;
            }
            if (!value(c, depth + 1, child))
                return false;
            if (child)
                child = child->next;
            whitespace(c);
            if (take(c, close))
                return true;
        } while (take(c, ','));
        return false;
    }
    if (ch == '"')
        return string(c);
    const char *literal = ch == 't' ? "true" : ch == 'f' ? "false" : ch == 'n' ? "null" : NULL;
    if (literal) {
        size_t n = strlen(literal);
        if ((size_t)(c->end - c->p) < n || memcmp(c->p, literal, n))
            return false;
        c->p += n;
        return true;
    }
    return number(c, tree);
}

static bool unique_tree(const cJSON *v)
{
    if (cJSON_IsNumber(v) && !isfinite(v->valuedouble))
        return false;
    for (const cJSON *a = v->child; a; a = a->next) {
        if (cJSON_IsObject(v)) {
            for (const cJSON *b = a->next; b; b = b->next)
                if (!strcmp(a->string, b->string))
                    return false;
        }
        if (!unique_tree(a))
            return false;
    }
    return true;
}

cJSON *strict_json_object(const char *line, size_t length)
{
    if (!line || !length || length >= 4096 || line[length] != '\0' ||
        !utf8((const unsigned char *)line, length))
        return NULL;
    cursor c = {(const unsigned char *)line, (const unsigned char *)line + length};
    if (!value(&c, 0, NULL))
        return NULL;
    whitespace(&c);
    if (c.p != c.end)
        return NULL;
    const char *end = NULL;
    cJSON *object = cJSON_ParseWithLengthOpts(line, length + 1, &end, true);
    if (!cJSON_IsObject(object) || end != line + length || !unique_tree(object)) {
        cJSON_Delete(object);
        return NULL;
    }
    c.p = (const unsigned char *)line;
    if (!value(&c, 0, object)) {
        cJSON_Delete(object);
        return NULL;
    }
    return object;
}

bool strict_json_integer(const cJSON *value)
{
    return cJSON_IsNumber(value) && (value->type & INTEGER_TOKEN) != 0;
}
