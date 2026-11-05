#if defined(__linux__)
#define _POSIX_C_SOURCE 200809L
#endif
#include <doc2struct/doc2struct.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#elif defined(__APPLE__)
#include <mach-o/dyld.h>
#else
#include <unistd.h>
#endif

/* Release bundles keep the private PDF engine beside this executable. Resolve
 * the executable itself so invoking it through PATH works from any directory. */
static int init_pdfium(doc2struct_error *error) {
    const char *override=getenv("DOC2STRUCT_PDFIUM_LIBRARY");
    char path[32768],*last,*other;
    size_t length;
    if(override&&*override)return doc2struct_pdfium_init(override,error);
#ifdef _WIN32
    wchar_t wide[32768];
    DWORD n=GetModuleFileNameW(NULL,wide,32768);
    if(!n||n>=32768||!WideCharToMultiByte(CP_UTF8,0,wide,-1,path,sizeof(path),NULL,NULL))goto failed;
#elif defined(__APPLE__)
    uint32_t n=sizeof(path);
    if(_NSGetExecutablePath(path,&n))goto failed;
    char resolved[32768];
    if(!realpath(path,resolved))goto failed;
    strcpy(path,resolved);
#else
    ssize_t n=readlink("/proc/self/exe",path,sizeof(path)-1);
    if(n<0||(size_t)n>=sizeof(path)-1)goto failed;
    path[n]=0;
#endif
    last=strrchr(path,'/');other=strrchr(path,'\\');
    if(other&&(!last||other>last))last=other;
    if(!last)goto failed;
    last[1]=0;length=strlen(path);
#ifdef _WIN32
    const char *library="doc2struct_pdfium.dll";
#elif defined(__APPLE__)
    const char *library="doc2struct_pdfium.dylib";
#else
    const char *library="doc2struct_pdfium.so";
#endif
    if(length+strlen(library)>=sizeof(path))goto failed;
    strcpy(path+length,library);
    return doc2struct_pdfium_init(path,error);
failed:
    snprintf(error->message,sizeof(error->message),"Cannot locate bundled PDFium; set DOC2STRUCT_PDFIUM_LIBRARY to its full path");
    return 0;
}

static char *read_file(const char *name,size_t *size) {
    FILE *f=fopen(name,"rb");long n;char *p;
    if(!f)return NULL;
    if(fseek(f,0,SEEK_END)||(n=ftell(f))<0||fseek(f,0,SEEK_SET)){fclose(f);return NULL;}
    p=malloc((size_t)n+1);if(!p){fclose(f);return NULL;}
    if(fread(p,1,(size_t)n,f)!=(size_t)n){free(p);fclose(f);return NULL;}
    fclose(f);p[n]=0;*size=(size_t)n;return p;
}
int main(int argc,char **argv) {
    doc2struct_error error={{0}};doc2struct_rules *rules=NULL;doc2struct_parser *parser=NULL;
    doc2struct_document *document=NULL;char *input=NULL,*config=NULL,*json=NULL;size_t n=0,length=0;int rc=1;
    if(argc==3&&!strcmp(argv[1],"--preset-json")) {
        json=doc2struct_rules_resolve(argv[2],strlen(argv[2]),1,&length,&error);
        if(!json){fprintf(stderr,"%s\n",error.message);return 1;}
        rc=fwrite(json,1,length,stdout)==length?0:1;doc2struct_buffer_free(json);return rc;
    }
    if(argc<2||argc>4){fprintf(stderr,"usage: doc2struct_parse input.html|input.pdf [NAMESPACE:TYPE | --rules config.json]\n");return 2;}
    input=read_file(argv[1],&n);if(!input){fprintf(stderr,"cannot read %s\n",argv[1]);goto done;}
    if(argc==4&&!strcmp(argv[2],"--rules")) {
        config=read_file(argv[3],&length);if(!config){fprintf(stderr,"cannot read rules\n");goto done;}
        rules=doc2struct_rules_json(config,length,&error);
    }else if(argc<=3)rules=doc2struct_rules_preset(argc==3?argv[2]:NULL,&error);
    else {fprintf(stderr,"invalid arguments\n");goto done;}
    if(!rules)goto failed;
    parser=doc2struct_parser_new(DOC2STRUCT_DEFAULT_CACHE_SIZE,&error);if(!parser)goto failed;
    if(n>=5&&!memcmp(input,"%PDF-",5)) {
        if(!init_pdfium(&error))goto failed;
        document=doc2struct_parse_pdf(parser,(doc2struct_string){input,n},rules,&error);
    } else document=doc2struct_parse(parser,(doc2struct_string){input,n},rules,&error);
    if(!document)goto failed;
    json=doc2struct_document_json(document,rules,argc>2,&length,&error);if(!json)goto failed;
    rc=fwrite(json,1,length,stdout)==length?0:1;goto done;
failed:fprintf(stderr,"%s\n",error.message);
done:
    doc2struct_buffer_free(json);doc2struct_document_free(document);doc2struct_parser_free(parser);
    doc2struct_rules_free(rules);free(input);free(config);return rc;
}
