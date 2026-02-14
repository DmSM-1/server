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
    
    if (connect(sfd, (struct sockaddr *) &server_addr, sizeof(server_addr)) == -1)
    handle_error("connect");
    
    char buf[1025];
    char filename[128] = "Fly Me To The Moon.mp3";
    FILE* file = fopen(filename, "rb");


    buf[0] = 1;
    memcpy(buf, filename, 128);
    send(sfd, buf, 1025, 0);

    buf[0] = 2;
    while (fread(buf+1, 1, 1024, file)){
        send(sfd, buf, 1025, 0);
    }

    buf[0] = 3;
    send(sfd, buf, 1025, 0);

    close(sfd);

    return 0;
}