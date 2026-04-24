FROM debian:trixie

RUN apt-get update
RUN apt-get -y install git
RUN apt-get -y install yq
RUN apt-get -y install zsh
RUN apt-get -y install python3

# Setup User
RUN useradd -ms /bin/bash conflict-playground
USER conflict-playground
WORKDIR /home/conflict-playground

# Setup caches volume
ADD src src
USER root
RUN mkdir -p /home/conflict-playground/caches
RUN chown -R conflict-playground:conflict-playground /home/conflict-playground/caches
USER conflict-playground


ENTRYPOINT ["tail", "-f", "/dev/null"]