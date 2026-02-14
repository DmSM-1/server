#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
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
#define min(a,b) ((long long)a>(long long)b)?(long long)b:(long long)a
#define payload 1024*16
#define packet_size (payload+4)
#define times 4

#ifdef DEBUG
    #define SERVER_IP inet_addr("127.0.0.10")
#else
    #define SERVER_IP inet_addr("95.181.175.77")
#endif

#define handle_error(msg) \
           do { perror(msg); exit(EXIT_FAILURE); } while (0)


sem_t init_tx;
sem_t init_rx;  
sem_t end_tx;           
sem_t end_rx;           


void clear_dir(const char *path) {
    DIR *d = opendir(path);
    if (!d) return;

    struct dirent *entry;
    char full_path[payload];
    struct stat st;

    while ((entry = readdir(d)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) continue;

        snprintf(full_path, sizeof(full_path), "%s/%s", path, entry->d_name);
        if (stat(full_path, &st) == -1) continue;

        if (S_ISREG(st.st_mode)) {
            unlink(full_path);
        }
    }
    closedir(d);
}

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


void* pc_handler(void* args){

    struct sockaddr_in server_addr, client_addr;
    
    server_addr.sin_family       = AF_INET;
    server_addr.sin_addr.s_addr  = SERVER_IP;
    server_addr.sin_port         = 2000;

    int sfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sfd == -1)
        handle_error("socket");
    int flag = 1;
    setsockopt(sfd, IPPROTO_TCP, TCP_NODELAY, (char *)&flag, sizeof(int));
    

    if (bind(sfd, (struct sockaddr *) &server_addr, sizeof(server_addr)) == -1)
        handle_error("bind");

    for (int iter = 0; iter < times; iter++){
    
        listen(sfd, 1);
            int cl_size = sizeof(client_addr);

        int confd = accept(sfd, (struct sockaddr *) &server_addr, &cl_size);

        printf("PC Connection was established\n");

        char buf[packet_size];
        char filename[128] = "buf/";
        char name[128];
        char file_open = 0;
        FILE* file;

        int pos = 0;
        int readed = 0;
        long long size = 0;
        int num_dirs = 0;

        while ((readed = recv(confd, buf+pos, packet_size - pos, 0))>0){
            pos += readed;

            if (pos < packet_size){
                continue;
            }

            if (memcmp(buf, "INIT", 4) == 0){
                printf("PC: INIT\n");
                clear_dir("./buf/rx");
                clear_dir("./buf/tx");
            }
            else if (memcmp(buf, "CONF", 4) == 0 && file_open == 0){
                printf("PC: CONF\n");
                memcpy((char*)&size,buf+4, sizeof(size));
                sprintf(filename, "buf/cfg");
                file = fopen(filename, "wb");
                file_open = 1;
            }
            else if (memcmp(buf, "FILE", 4) == 0 && file_open == 0){
                sprintf(filename, "buf/tx/%s", buf+4+sizeof(size));
                printf("PC: FILE %s\n", filename);
                memcpy((char*)&size,buf+4, sizeof(size));
                file = fopen(filename, "wb");
                file_open = 1;
                num_dirs++;
            }
            else if (memcmp(buf, "WRIT", 4) == 0 && file_open == 1){
                fwrite(buf+4, 1, min(size, payload), file);
                size -= min(size, payload);
            }
            else if (memcmp(buf, "CLOS", 4) == 0 && file_open == 1){
                printf("PC: CLOSE %s\n", filename);
                fclose(file); 
                file_open = 0;
            }
            else if (memcmp(buf, "STAR", 4) == 0){
                printf("PC: START\n");
                if (file_open == 1){
                    fclose(file); 
                    file_open = 0;
                }
                break;
            }
            memmove(buf, buf+packet_size, pos-packet_size);
            pos -= packet_size;
        }

        printf("PC: INIT END\n");
        
        
        sem_post(&init_tx);
        sem_post(&init_rx);
        
        sem_wait(&end_tx);
        sem_wait(&end_rx);
        
        for (int i = 1; i < num_dirs+1; i++){
            sprintf(filename, "buf/tx/%d", i);
            sprintf(name, "%d", i);
            send_file(confd, filename, name, "FILE", packet_size, buf);
        }
        send_cmd(confd, "STAR", packet_size, buf);
        
        close(confd);

    }

    close(sfd);

    return NULL;
}

void* tx_handler(void* args){
    for (int iter = 0; iter < times; iter++){
        sem_wait(&init_tx);
        sem_post(&end_tx);
    }
    return NULL;
}

void* rx_handler(void* args){
    for (int iter = 0; iter < times; iter++){
        sem_wait(&init_rx);
        sem_post(&end_rx);
    }
    return NULL;
}


int main(int argc, char** argv){

    sem_init(&init_tx, 0, 0);  
    sem_init(&init_rx, 0, 0);  
    sem_init(&end_tx, 0, 0);  
    sem_init(&end_rx, 0, 0);  

    pthread_t pc_thread, tx_thread, rx_thread;

    pthread_create(&pc_thread, NULL, pc_handler, NULL);
    pthread_create(&tx_thread, NULL, tx_handler, NULL);
    pthread_create(&rx_thread, NULL, rx_handler, NULL);


    pthread_join(pc_thread, NULL);
    pthread_join(tx_thread, NULL);
    pthread_join(rx_thread, NULL);

    sem_destroy(&init_tx);
    sem_destroy(&init_rx);


    return 0;
}