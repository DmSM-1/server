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
    
    char* buf = malloc(1024);

    read(0, buf, 1024);
    send(sfd, buf, 1024, 0);

    free(buf);
    close(sfd);

    return 0;
}