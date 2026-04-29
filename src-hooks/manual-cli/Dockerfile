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
RUN apt-get -y install vim

ADD src-hooks/entrypoint-base.sh entrypoint-base.sh
ADD src-hooks/manual-cli/entrypoint.py entrypoint.py
ADD src-hooks/hooks_common.py hooks_common.py
ADD assets/hooks/* .