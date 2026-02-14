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


#define SERVER_IP inet_addr("95.181.175.77")
// #define SERVER_IP inet_addr("127.0.0.1")

#define handle_error(msg) \
           do { perror(msg); exit(EXIT_FAILURE); } while (0)


int main(int argc, char** argv){

    struct sockaddr_in server_addr, client_addr;
    
    server_addr.sin_family       = AF_INET;
    server_addr.sin_addr.s_addr  = SERVER_IP;
    server_addr.sin_port         = 2000;

    int sfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sfd == -1)
        handle_error("socket");

    if (bind(sfd, (struct sockaddr *) &server_addr, sizeof(server_addr)) == -1)
        handle_error("bind");

    listen(sfd, 1);

    int cl_size = sizeof(client_addr);

    int confd = accept(sfd, (struct sockaddr *) &server_addr, &cl_size);

    printf("Connection was established\n");

    int stage = 0;
    char buf[1025];
    char filename[128] = "buf/";
    FILE* file;

    while (recv(confd, buf, 1025, 0)>0){
        switch (buf[0]){

            case 1: 
                printf("eee\n");
                memcpy(filename+4, buf+1, 128); 
                printf("Open file %s\n", filename);
                
                file = fopen(filename, "wb"); 
            break;

            case 2: fwrite(buf+1, 1, 1024, file); break;

            case 3: 
                printf("Close file %s\n", filename);
                fclose(file); 
            break;

        default: break;
        }
    }

    close(confd);
    close(sfd);

    return 0;
}