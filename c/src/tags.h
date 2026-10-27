#ifndef DOC2STRUCT_TAGS_H
#define DOC2STRUCT_TAGS_H
#include "doc2struct.h"

enum {
    T_VOID = 1u << 0,
    T_LINE = 1u << 1,
    T_BLOCK = 1u << 2,
    T_HEAD = 1u << 3,
    T_P_CLOSE = 1u << 4,
    T_CELL = 1u << 5,
    T_TR = 1u << 6,
    T_TABLE = 1u << 7,
    T_SECTION = 1u << 8,
    T_LI = 1u << 9,
    T_DTDD = 1u << 10,
    T_LIST = 1u << 11,
    T_DL = 1u << 12,
    T_BODY_HTML = 1u << 13,
    T_BOLD = 1u << 14,
    T_ITALIC = 1u << 15,
    T_UNDER = 1u << 16,
    T_A = 1u << 17,
    T_BR = 1u << 18,
    T_IMG = 1u << 19,
    T_P = 1u << 20
};

/* Dispatch on bounded byte keys. Common tags need no strlen or memcmp. */
static inline unsigned ds_tag_flags(Str tag) {
    uint64_t key;
    switch (tag.n) {
    case 1:
        key = ((uint64_t)(unsigned char)tag.p[0] << 0);
        switch (key) {
        case 0x70ULL:
            return T_LINE | T_BLOCK | T_P_CLOSE | T_P;
        case 0x62ULL:
            return T_BOLD;
        case 0x69ULL:
            return T_ITALIC;
        case 0x75ULL:
            return T_UNDER;
        case 0x61ULL:
            return T_A;
        }
        break;
    case 2:
        key = ((uint64_t)(unsigned char)tag.p[0] << 8) | ((uint64_t)(unsigned char)tag.p[1] << 0);
        switch (key) {
        case 0x6272ULL:
            return T_VOID | T_BR;
        case 0x6872ULL:
            return T_VOID | T_P_CLOSE;
        case 0x6831ULL:
            return T_LINE | T_BLOCK | T_P_CLOSE;
        case 0x6832ULL:
            return T_LINE | T_BLOCK | T_P_CLOSE;
        case 0x6833ULL:
            return T_LINE | T_BLOCK | T_P_CLOSE;
        case 0x6834ULL:
            return T_LINE | T_BLOCK | T_P_CLOSE;
        case 0x6835ULL:
            return T_LINE | T_BLOCK | T_P_CLOSE;
        case 0x6836ULL:
            return T_LINE | T_BLOCK | T_P_CLOSE;
        case 0x6c69ULL:
            return T_LINE | T_BLOCK | T_P_CLOSE | T_LI;
        case 0x7464ULL:
            return T_BLOCK | T_CELL;
        case 0x7468ULL:
            return T_BLOCK | T_CELL;
        case 0x646cULL:
            return T_P_CLOSE | T_DL;
        case 0x6464ULL:
            return T_P_CLOSE | T_DTDD;
        case 0x6474ULL:
            return T_P_CLOSE | T_DTDD;
        case 0x6f6cULL:
            return T_P_CLOSE | T_LIST;
        case 0x756cULL:
            return T_P_CLOSE | T_LIST;
        case 0x7472ULL:
            return T_TR;
        case 0x656dULL:
            return T_ITALIC;
        }
        break;
    case 3:
        key = ((uint64_t)(unsigned char)tag.p[0] << 16) | ((uint64_t)(unsigned char)tag.p[1] << 8) |
              ((uint64_t)(unsigned char)tag.p[2] << 0);
        switch (key) {
        case 0x636f6cULL:
            return T_VOID;
        case 0x696d67ULL:
            return T_VOID | T_IMG;
        case 0x776272ULL:
            return T_VOID;
        case 0x646976ULL:
            return T_LINE | T_BLOCK | T_P_CLOSE;
        case 0x646972ULL:
            return T_P_CLOSE;
        case 0x6e6176ULL:
            return T_P_CLOSE;
        case 0x707265ULL:
            return T_P_CLOSE;
        case 0x696e73ULL:
            return T_UNDER;
        }
        break;
    case 4:
        key = ((uint64_t)(unsigned char)tag.p[0] << 24) |
              ((uint64_t)(unsigned char)tag.p[1] << 16) | ((uint64_t)(unsigned char)tag.p[2] << 8) |
              ((uint64_t)(unsigned char)tag.p[3] << 0);
        switch (key) {
        case 0x61726561ULL:
            return T_VOID;
        case 0x62617365ULL:
            return T_VOID | T_HEAD;
        case 0x6c696e6bULL:
            return T_VOID | T_HEAD;
        case 0x6d657461ULL:
            return T_VOID | T_HEAD;
        case 0x68746d6cULL:
            return T_HEAD | T_BODY_HTML;
        case 0x68656164ULL:
            return T_HEAD;
        case 0x666f726dULL:
            return T_P_CLOSE;
        case 0x6d61696eULL:
            return T_P_CLOSE;
        case 0x6d656e75ULL:
            return T_P_CLOSE;
        case 0x626f6479ULL:
            return T_BODY_HTML;
        }
        break;
    case 5:
        key = ((uint64_t)(unsigned char)tag.p[0] << 32) |
              ((uint64_t)(unsigned char)tag.p[1] << 24) |
              ((uint64_t)(unsigned char)tag.p[2] << 16) | ((uint64_t)(unsigned char)tag.p[3] << 8) |
              ((uint64_t)(unsigned char)tag.p[4] << 0);
        switch (key) {
        case 0x656d626564ULL:
            return T_VOID;
        case 0x696e707574ULL:
            return T_VOID;
        case 0x706172616dULL:
            return T_VOID;
        case 0x747261636bULL:
            return T_VOID;
        case 0x7469746c65ULL:
            return T_HEAD;
        case 0x7374796c65ULL:
            return T_HEAD;
        case 0x6173696465ULL:
            return T_P_CLOSE;
        case 0x7461626c65ULL:
            return T_P_CLOSE | T_TABLE;
        case 0x7468656164ULL:
            return T_SECTION;
        case 0x74626f6479ULL:
            return T_SECTION;
        case 0x74666f6f74ULL:
            return T_SECTION;
        }
        break;
    case 6:
        key =
            ((uint64_t)(unsigned char)tag.p[0] << 40) | ((uint64_t)(unsigned char)tag.p[1] << 32) |
            ((uint64_t)(unsigned char)tag.p[2] << 24) | ((uint64_t)(unsigned char)tag.p[3] << 16) |
            ((uint64_t)(unsigned char)tag.p[4] << 8) | ((uint64_t)(unsigned char)tag.p[5] << 0);
        switch (key) {
        case 0x736f75726365ULL:
            return T_VOID;
        case 0x736372697074ULL:
            return T_HEAD;
        case 0x63656e746572ULL:
            return T_P_CLOSE;
        case 0x6469616c6f67ULL:
            return T_P_CLOSE;
        case 0x666967757265ULL:
            return T_P_CLOSE;
        case 0x666f6f746572ULL:
            return T_P_CLOSE;
        case 0x686561646572ULL:
            return T_P_CLOSE;
        case 0x6867726f7570ULL:
            return T_P_CLOSE;
        case 0x7374726f6e67ULL:
            return T_BOLD;
        }
        break;
    case 7:
        key =
            ((uint64_t)(unsigned char)tag.p[0] << 48) | ((uint64_t)(unsigned char)tag.p[1] << 40) |
            ((uint64_t)(unsigned char)tag.p[2] << 32) | ((uint64_t)(unsigned char)tag.p[3] << 24) |
            ((uint64_t)(unsigned char)tag.p[4] << 16) | ((uint64_t)(unsigned char)tag.p[5] << 8) |
            ((uint64_t)(unsigned char)tag.p[6] << 0);
        switch (key) {
        case 0x61646472657373ULL:
            return T_P_CLOSE;
        case 0x61727469636c65ULL:
            return T_P_CLOSE;
        case 0x64657461696c73ULL:
            return T_P_CLOSE;
        case 0x73656374696f6eULL:
            return T_P_CLOSE;
        case 0x73756d6d617279ULL:
            return T_P_CLOSE;
        }
        break;
    case 8:
        key =
            ((uint64_t)(unsigned char)tag.p[0] << 56) | ((uint64_t)(unsigned char)tag.p[1] << 48) |
            ((uint64_t)(unsigned char)tag.p[2] << 40) | ((uint64_t)(unsigned char)tag.p[3] << 32) |
            ((uint64_t)(unsigned char)tag.p[4] << 24) | ((uint64_t)(unsigned char)tag.p[5] << 16) |
            ((uint64_t)(unsigned char)tag.p[6] << 8) | ((uint64_t)(unsigned char)tag.p[7] << 0);
        switch (key) {
        case 0x6e6f736372697074ULL:
            return T_HEAD;
        case 0x6669656c64736574ULL:
            return T_P_CLOSE;
        }
        break;
    case 10:
        if (ds_is(tag, "blockquote"))
            return T_P_CLOSE;
        if (ds_is(tag, "figcaption"))
            return T_P_CLOSE;
        break;
    }
    return 0;
}
#endif
