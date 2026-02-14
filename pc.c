#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/un.h>
#include <unistd.h>
#include <semaphore.h>
#include <pthread.h>
#include <dirent.h>

// #define DEBUG

#ifdef DEBUG
    #define SERVER_IP inet_addr("127.0.0.10")
#else
    #define SERVER_IP inet_addr("95.181.175.77")
#endif

#define min(a,b) ((long long)a>(long long)b)?(long long)b:(long long)a
#define handle_error(msg) \
           do { perror(msg); exit(EXIT_FAILURE); } while (0)


void robust_send(int sfd, char* buf, size_t size){
    int sent;
    for(int i = 0; i < size;){
        sent = send(sfd, buf+i, size-i, 0);
        if (sent<0)
            handle_error("robust_send");
        i += sent;
    }
}

int count_subdirectories(const char *path) {
    struct dirent *entry;
    DIR *d = opendir(path);
    
    if (d == NULL) return -1;

    int count = 0;
    while ((entry = readdir(d)) != NULL) {
        if (entry->d_type == DT_DIR) {
            if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
                continue;
            }
            count++;
        }
    }
    closedir(d);
    return count;
}

void send_file(int sfd, char* filename, char* name, char* filetype, size_t size, char* buf){
    struct stat st;

    stat(filename, &st);
    long long filesize = (long long)st.st_size;

    memcpy(buf, filetype, 4);
    memcpy(buf+4, (char*)(&filesize), sizeof(filesize));  
    memcpy(buf+4+sizeof(filesize), name, 128);

    robust_send(sfd, buf, size);

    sprintf(buf, "WRIT");
    FILE* file = fopen(filename, "rb");
    while (fread(buf+4, 1, size-4, file)) robust_send(sfd, buf, size);
    fclose(file);

    sprintf(buf, "CLOS");
    robust_send(sfd, buf, size);
}

void send_cmd(int sfd, char* cmd, size_t size, char* buf){
    memcpy(buf, cmd, 4);
    robust_send(sfd, buf, size);
}

int main(int argc, char** argv){
    struct sockaddr_in server_addr, client_addr;

    server_addr.sin_family       = AF_INET;
    server_addr.sin_addr.s_addr  = SERVER_IP;
    server_addr.sin_port         = 2000;

    int num_dirs = count_subdirectories("pc_dir");

    int sfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sfd == -1)
    handle_error("socket");
    
    if (connect(sfd, (struct sockaddr *) &server_addr, sizeof(server_addr)) == -1)
    handle_error("connect");
    
    char buf[2056];
    char filename[128];
    char name[128];

    send_cmd(sfd, "INIT", 1028, buf);
    send_file(sfd, "pc_dir/config.mat", "cfg", "CONF", 1028, buf);
    
    for (int i = 1; i < num_dirs+1; i++){   
        sprintf(filename, "pc_dir/%d/tx_data.mat", i);
        sprintf(name, "%d", i);
        send_file(sfd, filename, name, "FILE", 1028, buf);
    }

    send_cmd(sfd, "STAR", 1028, buf);

    int pos = 0;
    int readed = 0;
    long long size = 0;
    num_dirs = 0;
    char file_open = 0;
    FILE* file;


    while ((readed = recv(sfd, buf+pos, 1028 - pos, 0))>0){
        pos += readed;

        if (pos < 1028){
            continue;
        }

        if (memcmp(buf, "FILE", 4) == 0 && file_open == 0){
            num_dirs++;
            memcpy((char*)&size,buf+4, sizeof(size));
            sprintf(filename, "pc_dir/%d/%d", num_dirs, num_dirs);
            file = fopen(filename, "wb");
            printf("PC: FILE %s\n", filename);
            file_open = 1;
        }
        else if (memcmp(buf, "WRIT", 4) == 0 && file_open == 1){
            fwrite(buf+4, 1, min(size, 1024), file);
            size -= min(size, 1024);
        }
        else if (memcmp(buf, "CLOS", 4) == 0 && file_open == 1){
            printf("PC: CLOSE %s\n", filename);
            fclose(file); 
            file_open = 0;
        }
        else if (memcmp(buf, "STAR", 4) == 0){
            printf("PC: END\n");
            if (file_open == 1){
                fclose(file); 
                file_open = 0;
            }
            break;
        }
        memmove(buf, buf+1028, pos-1028);
        pos -= 1028;
    }


    close(sfd);
}