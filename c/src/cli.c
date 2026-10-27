#include <doc2struct/doc2struct.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
    if(argc<2||argc>4){fprintf(stderr,"usage: doc2struct_parse input.html [NAMESPACE:TYPE | --rules config.json]\n");return 2;}
    input=read_file(argv[1],&n);if(!input){fprintf(stderr,"cannot read %s\n",argv[1]);goto done;}
    if(argc==4&&!strcmp(argv[2],"--rules")) {
        config=read_file(argv[3],&length);if(!config){fprintf(stderr,"cannot read rules\n");goto done;}
        rules=doc2struct_rules_json(config,length,&error);
    }else if(argc<=3)rules=doc2struct_rules_preset(argc==3?argv[2]:NULL,&error);
    else {fprintf(stderr,"invalid arguments\n");goto done;}
    if(!rules)goto failed;
    parser=doc2struct_parser_new(DOC2STRUCT_DEFAULT_CACHE_SIZE,&error);if(!parser)goto failed;
    document=doc2struct_parse(parser,(doc2struct_string){input,n},rules,doc2struct_options_default(),&error);
    if(!document)goto failed;
    json=doc2struct_document_json(document,rules,argc>2,&length,&error);if(!json)goto failed;
    rc=fwrite(json,1,length,stdout)==length?0:1;goto done;
failed:fprintf(stderr,"%s\n",error.message);
done:
    doc2struct_buffer_free(json);doc2struct_document_free(document);doc2struct_parser_free(parser);
    doc2struct_rules_free(rules);free(input);free(config);return rc;
}
