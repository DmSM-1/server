#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>


#define SERVER_IP inet_addr("95.181.175.77")


int main(int argc, char** argv){

    struct sockaddr_in server_addr, client_addr;

    char* buf = malloc(1024);

    server_addr.sin_family       = AF_INET;
    server_addr.sin_addr.s_addr  = SERVER_IP;
    server_addr.sin_port         = 2000;

    int sfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sfd == -1)
        handle_error("socket");

    if (bind(sfd, (struct sockaddr *) &server_addr, sizeof(server_addr)) == -1)
        handle_error("bind");

    listen(sfd, 1);

    size_t cl_size = sizeof(client_addr);

    int confd = accept(sfd, (struct sockaddr *) &server_addr, &cl_size);

    recv(confd, buf, 1024, 0);
    
    printf("%s\n", buf);

    close(confd);
    close(sfd);

    return 0;
}