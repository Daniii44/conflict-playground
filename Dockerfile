FROM debian:trixie

RUN apt-get update
RUN apt-get -y install git
RUN apt-get -y install yq

RUN useradd -ms /bin/bash conflict-playground
USER conflict-playground
WORKDIR /home/conflict-playground

ADD src src

ENTRYPOINT ["tail", "-f", "/dev/null"]