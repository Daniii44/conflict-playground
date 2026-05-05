FROM debian:trixie
WORKDIR /root
ENTRYPOINT ["tail", "-f", "/dev/null"]

RUN apt-get update
RUN apt-get -y install git
RUN apt-get -y install yq
RUN apt-get -y install zsh
RUN apt-get -y install python3
RUN apt-get -y install python3-redis
RUN apt-get -y install python3-pydantic
RUN apt-get -y install python3-rich

ADD src-playground src
ADD assets/playground/* .