#ifndef DOC2STRUCT_CONFIG_JSON_H
#define DOC2STRUCT_CONFIG_JSON_H
#include "doc2struct.h"
enum { J_NULL, J_BOOL, J_NUMBER, J_STRING, J_ARRAY, J_OBJECT };
typedef struct JValue {
    int type, boolean;
    Str key, text;
    struct JValue *child, *next;
    size_t count;
} JValue;
JValue *ds_config_parse(Arena *, Str);
JValue *ds_config_get(JValue *, const char *);
void ds_config_merge(Arena *, JValue *, const JValue *);
Str ds_config_write(Arena *, const JValue *);
int ds_config_equal(const JValue *, const JValue *);
#endif
