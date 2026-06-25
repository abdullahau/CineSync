import socket


def force_ipv4():
    orig = socket.getaddrinfo

    def getaddrinfo_ipv4(*args, **kwargs):
        return [x for x in orig(*args, **kwargs) if x[0] == socket.AF_INET]

    socket.getaddrinfo = getaddrinfo_ipv4


force_ipv4()
