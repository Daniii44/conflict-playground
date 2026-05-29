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
RUN apt-get -y install python3-construct
RUN apt-get -y install python3-pytest
RUN apt-get -y install python3-loguru
RUN apt-get -y install python3-tqdm
RUN apt-get -y install python3-requests
RUN apt-get -y install python3-yaml
RUN apt-get -y install redis-tools
RUN apt-get -y install tree

ADD src-playground src
ADD assets/playground/* .