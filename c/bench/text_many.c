/* Public C API benchmark. Input loading, result hashing and rule preparation
 * are outside the timer. Parsing and document release are included. No PGO. */
#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200809L
#endif
#include <doc2struct/doc2struct.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
static double now(void) { LARGE_INTEGER t,f; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&t); return (double)t.QuadPart/(double)f.QuadPart; }
#else
#include <time.h>
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec*1e-9; }
#endif
typedef struct { char *p; size_t n; } Input;
static uint64_t number(uint64_t h, uint64_t value) { int i; for(i=0;i<8;i++){h^=value&255;h*=UINT64_C(1099511628211);value>>=8;}return h; }
static uint64_t text_hash(uint64_t h,doc2struct_string s) {size_t i;h=number(h,s.n);for(i=0;i<s.n;i++){h^=(unsigned char)s.p[i];h*=UINT64_C(1099511628211);}return h;}
static uint64_t result_hash(uint64_t h,const doc2struct_document *d) {
    size_t i,j,n;const doc2struct_row *r=doc2struct_document_rows(d,&n);h=number(h,n);
    for(i=0;i<n;i++) {
        h=number(h,r[i].id);h=number(h,r[i].level);h=number(h,(uint64_t)r[i].cleaned);
        h=text_hash(h,r[i].type);h=text_hash(h,r[i].klass);h=text_hash(h,r[i].title);h=text_hash(h,r[i].text);
        h=text_hash(h,r[i].preamble);h=text_hash(h,r[i].postamble);h=number(h,r[i].matrix.nr);h=number(h,r[i].matrix.nc);
        for(j=0;j<r[i].matrix.nr*r[i].matrix.nc;j++)h=text_hash(h,r[i].matrix.cells[j]);
        h=number(h,r[i].nnotes);for(j=0;j<r[i].nnotes;j++){h=text_hash(h,r[i].notes[j].id);h=text_hash(h,r[i].notes[j].text);}
    }return h;
}
static int compare(const void *a,const void *b){double x=*(const double *)a,y=*(const double *)b;return (x>y)-(x<y);}
int main(int argc,char **argv) {
    FILE *manifest,*f;char path[8192];Input *inputs=NULL;size_t count=0,capacity=0,total=0,i;int mode,round,rounds=argc>2?atoi(argv[2]):7;
    doc2struct_error error;doc2struct_rules *rules;doc2struct_parser *parser;
    if(argc<2||rounds<1||rounds>100){fprintf(stderr,"Usage: %s manifest.txt [rounds:1..100]\n",argv[0]);return 1;}
    manifest=fopen(argv[1],"rb");if(!manifest){perror(argv[1]);return 1;}
    while(fgets(path,sizeof(path),manifest)) {
        long size;size_t length=strcspn(path,"\r\n");char *buffer;path[length]=0;if(!length)continue;
        f=fopen(path,"rb");if(!f){perror(path);return 1;}if(fseek(f,0,SEEK_END)||(size=ftell(f))<0||fseek(f,0,SEEK_SET)){fclose(f);return 1;}
        buffer=malloc((size_t)size+1);if(!buffer)return 1;if(fread(buffer,1,(size_t)size,f)!=(size_t)size){fclose(f);return 1;}fclose(f);buffer[size]=0;
        if(count==capacity){Input *grown;capacity=capacity?capacity*2:64;grown=realloc(inputs,capacity*sizeof(Input));if(!grown)return 1;inputs=grown;}
        inputs[count++]=(Input){buffer,(size_t)size};total+=(size_t)size;
    }fclose(manifest);if(!count){fprintf(stderr,"Empty manifest\n");return 1;}
    rules=doc2struct_rules_preset(NULL,&error);parser=doc2struct_parser_new(DOC2STRUCT_DEFAULT_CACHE_SIZE,&error);
    if(!rules||!parser){fprintf(stderr,"%s\n",error.message);return 1;}
    for(mode=0;mode<2;mode++) {
        double samples[100];uint64_t expected=0;
        doc2struct_document *warm=mode?doc2struct_parse_partialsgml(parser,(doc2struct_string){inputs[0].p,inputs[0].n},rules,&error):doc2struct_parse_text(parser,(doc2struct_string){inputs[0].p,inputs[0].n},rules,&error);
        if(!warm){fprintf(stderr,"%s\n",error.message);return 1;}doc2struct_document_free(warm);
        for(round=0;round<rounds;round++) {
            double elapsed=0;uint64_t hash=UINT64_C(14695981039346656037);
            for(i=0;i<count;i++) {
                double start=now();doc2struct_string input={inputs[i].p,inputs[i].n};
                doc2struct_document *d=mode?doc2struct_parse_partialsgml(parser,input,rules,&error):doc2struct_parse_text(parser,input,rules,&error);
                elapsed+=now()-start;if(!d){fprintf(stderr,"Input %zu: %s\n",i,error.message);return 1;}
                hash=result_hash(hash,d);
                start=now();doc2struct_document_free(d);elapsed+=now()-start;
            }samples[round]=elapsed;if(round&&expected!=hash){fprintf(stderr,"Unstable results\n");return 1;}expected=hash;
        }
        qsort(samples,(size_t)rounds,sizeof(double),compare);
        printf("%s: files=%zu bytes=%zu rounds=%d median_ms=%.3f MB/s=%.3f hash=%016llx\n",mode?"partialsgml":"text",count,total,rounds,samples[rounds/2]*1000,total/1e6/samples[rounds/2],(unsigned long long)expected);
        fflush(stdout);
    }
    doc2struct_parser_free(parser);doc2struct_rules_free(rules);for(i=0;i<count;i++)free(inputs[i].p);free(inputs);return 0;
}
