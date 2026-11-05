/* Standalone equivalent of test_many.py. Only doc2struct_parse is timed.
 * File reads, rules setup, row counting, and document cleanup are outside it.
 * Usage: doc2struct_bench [directory]; defaults to data/filings/many_10k.
 */
#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#define _FILE_OFFSET_BITS 64
#else
#define _CRT_SECURE_NO_WARNINGS
#endif
#include <doc2struct/doc2struct.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#ifdef _WIN32
#include <windows.h>
#include <wchar.h>
typedef wchar_t PathChar;
#define PATH(s) L##s
#define path_length wcslen
#define path_compare _wcsicmp
#define open_file(p) _wfopen(p, L"rb")
#define file_seek _fseeki64
#define file_tell _ftelli64
static LARGE_INTEGER frequency;
static double seconds(void) {
    LARGE_INTEGER tick;
    if (!QueryPerformanceCounter(&tick)) {
        fprintf(stderr, "Cannot read performance counter\n");
        exit(1);
    }
    return (double)tick.QuadPart / (double)frequency.QuadPart;
}
static void path_error(const char *message, const PathChar *path) {
    fprintf(stderr, "%s: %ls\n", message, path);
}
#else
#include <dirent.h>
#include <sys/stat.h>
#include <time.h>
#include <errno.h>
typedef char PathChar;
#define PATH(s) s
#define path_length strlen
#define path_compare strcmp
#define open_file(p) fopen(p, "rb")
#define file_seek fseeko
#define file_tell ftello
static double seconds(void) {
    struct timespec tick;
    if (clock_gettime(CLOCK_MONOTONIC, &tick)) {
        perror("clock_gettime");
        exit(1);
    }
    return (double)tick.tv_sec + (double)tick.tv_nsec / 1e9;
}
static void path_error(const char *message, const PathChar *path) {
    fprintf(stderr, "%s: %s\n", message, path);
}
#endif

typedef struct { PathChar **paths; size_t count, capacity; } Files;

static void *allocate(size_t size) {
    void *p = malloc(size);
    if (!p) { fprintf(stderr, "Out of memory\n"); exit(1); }
    return p;
}
static PathChar *join(const PathChar *directory, const PathChar *name) {
    size_t n = path_length(directory), m = path_length(name);
    PathChar *p;
    if (m > SIZE_MAX / sizeof(*p) - 2 || n > SIZE_MAX / sizeof(*p) - m - 2) {
        fprintf(stderr, "Path too long\n"); exit(1);
    }
    p = allocate((n + m + 2) * sizeof(*p));
    memcpy(p, directory, n * sizeof(*p));
    p[n] = '/';
    memcpy(p + n + 1, name, (m + 1) * sizeof(*p));
    return p;
}
static int html_file(const PathChar *path) {
    size_t n = path_length(path), i;
    char suffix[6] = {0};
    if (n < 4) return 0;
    /* ASCII case folding is sufficient for .htm/.html on either platform. */
    for (i = 0; i < 5 && i < n; i++) {
        unsigned c = (unsigned)path[n - i - 1];
        if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        suffix[i] = c < 128 ? (char)c : '?';
    }
    return !strncmp(suffix, "mth.", 4) || !strcmp(suffix, "lmth.");
}
static void append(Files *files, PathChar *path) {
    if (files->count == files->capacity) {
        size_t capacity = files->capacity ? files->capacity * 2 : 128;
        PathChar **next;
        if (capacity < files->capacity || capacity > SIZE_MAX / sizeof(*next)) {
            fprintf(stderr, "Too many files\n"); exit(1);
        }
        next = realloc(files->paths, capacity * sizeof(*next));
        if (!next) { fprintf(stderr, "Out of memory\n"); exit(1); }
        files->paths = next;
        files->capacity = capacity;
    }
    files->paths[files->count++] = path;
}
static int collect(Files *files, const PathChar *directory) {
    int ok = 1;
#ifdef _WIN32
    WIN32_FIND_DATAW entry;
    PathChar *pattern = join(directory, PATH("*"));
    HANDLE handle = FindFirstFileW(pattern, &entry);
    DWORD error;
    free(pattern);
    if (handle == INVALID_HANDLE_VALUE) {
        if (GetLastError() == ERROR_FILE_NOT_FOUND) return 1;
        path_error("Cannot enumerate directory", directory); return 0;
    }
    do {
        PathChar *path;
        if (!wcscmp(entry.cFileName, L".") || !wcscmp(entry.cFileName, L"..")) continue;
        path = join(directory, entry.cFileName);
        if (entry.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            /* Match pathlib.rglob: do not recurse into directory links. */
            if (!(entry.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) ok = collect(files, path);
        } else if (html_file(path)) {
            append(files, path);
            path = NULL;
        }
        free(path);
        if (!ok) break;
    } while (FindNextFileW(handle, &entry));
    error = GetLastError();
    FindClose(handle);
    if (ok && error != ERROR_NO_MORE_FILES) {
        path_error("Directory enumeration failed", directory); ok = 0;
    }
#else
    DIR *handle = opendir(directory);
    struct dirent *entry;
    if (!handle) { path_error("Cannot enumerate directory", directory); return 0; }
    for (;;) {
        PathChar *path;
        struct stat info;
        int linked;
        errno = 0;
        entry = readdir(handle);
        if (!entry) {
            if (errno) { path_error("Directory enumeration failed", directory); ok = 0; }
            break;
        }
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        path = join(directory, entry->d_name);
        if (lstat(path, &info)) { path_error("Cannot stat file", path); free(path); ok = 0; break; }
        linked = S_ISLNK(info.st_mode);
        if (linked && stat(path, &info)) { free(path); continue; }
        if (S_ISDIR(info.st_mode)) {
            if (!linked) ok = collect(files, path);
        } else if (S_ISREG(info.st_mode) && html_file(path)) {
            append(files, path);
            path = NULL;
        }
        free(path);
        if (!ok) break;
    }
    closedir(handle);
#endif
    return ok;
}
static int compare_files(const void *a, const void *b) {
    return path_compare(*(const PathChar *const *)a, *(const PathChar *const *)b);
}
static char *read_file(const PathChar *path, size_t *size) {
    FILE *file = open_file(path);
    int64_t length;
    char *data;
    if (!file) return NULL;
    if (file_seek(file, 0, SEEK_END) || (length = file_tell(file)) < 0 ||
        (uint64_t)length >= SIZE_MAX || file_seek(file, 0, SEEK_SET)) {
        fclose(file); return NULL;
    }
    data = allocate((size_t)length + 1);
    if (fread(data, 1, (size_t)length, file) != (size_t)length || ferror(file)) {
        free(data); fclose(file); return NULL;
    }
    fclose(file);
    data[length] = 0;
    *size = (size_t)length;
    return data;
}

#ifdef _WIN32
int wmain(int argc, wchar_t **argv) {
#else
int main(int argc, char **argv) {
#endif
    Files files = {0};
    doc2struct_error error;
    doc2struct_rules *rules = NULL;
    doc2struct_parser *parser = NULL;
    double total_time = 0;
    uint64_t total_bytes = 0, total_rows = 0;
    size_t i;
    int status = 1;
    if (argc > 2) {
        fprintf(stderr, "usage: doc2struct_bench [directory]\n"); return 2;
    }
#ifdef _WIN32
    if (!QueryPerformanceFrequency(&frequency)) {
        fprintf(stderr, "Cannot initialize performance counter\n"); return 1;
    }
#endif
    if (!collect(&files, argc == 2 ? argv[1] : PATH("data/filings/many_10k"))) goto done;
    if (!files.count) { fprintf(stderr, "No .htm or .html files found\n"); goto done; }
    qsort(files.paths, files.count, sizeof(*files.paths), compare_files);
    rules = doc2struct_rules_preset("SEC:10-K", &error);
    if (!rules) { fprintf(stderr, "%s\n", error.message); goto done; }
    parser = doc2struct_parser_new(DOC2STRUCT_DEFAULT_CACHE_SIZE, &error);
    if (!parser) { fprintf(stderr, "%s\n", error.message); goto done; }
    for (i = 0; i < files.count; i++) {
        size_t size, rows;
        char *data = read_file(files.paths[i], &size);
        doc2struct_document *document;
        double start;
        if (!data) { path_error("Cannot read file", files.paths[i]); goto done; }
        start = seconds();
        document = doc2struct_parse(parser, (doc2struct_string){data, size}, rules, &error);
        total_time += seconds() - start;
        if (!document) {
            path_error(error.message, files.paths[i]); free(data); goto done;
        }
        doc2struct_document_rows(document, &rows);
        total_rows += rows;
        total_bytes += size;
        doc2struct_document_free(document);
        free(data);
    }
    printf("Total parsing time for %zu files: %.3f seconds\n", files.count, total_time);
    printf("Total parsed: %.3f MB\n", (double)total_bytes / 1e6);
    printf("Throughput: %.3f MB/s\n", total_time > 0 ? (double)total_bytes / 1e6 / total_time : 0);
    printf("Total rows: %llu\n", (unsigned long long)total_rows);
    puts("Parsing only: excludes file I/O, rules setup, result cleanup, and Python/JSON export.");
    status = 0;
done:
    doc2struct_parser_free(parser);
    doc2struct_rules_free(rules);
    for (i = 0; i < files.count; i++) free(files.paths[i]);
    free(files.paths);
    return status;
}
