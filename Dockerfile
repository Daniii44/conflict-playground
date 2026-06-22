FROM eclipse-temurin:8-jdk AS java8
FROM eclipse-temurin:11-jdk AS java11
FROM eclipse-temurin:17-jdk AS java17

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
RUN apt-get -y install --no-install-recommends python3-pip
RUN pip3 install --break-system-packages --no-cache-dir langchain-ollama
RUN apt-get -y install redis-tools
RUN apt-get -y install tree

ADD src-playground src
ADD src-hooks src-hooks
ADD tests-playground tests-playground
ADD pyproject.toml .
ADD assets/playground/* .

COPY --from=java8 /opt/java/openjdk /opt/java/openjdk-8
COPY --from=java11 /opt/java/openjdk /opt/java/openjdk-11
COPY --from=java17 /opt/java/openjdk /opt/java/openjdk-17

ENV JAVA8_HOME=/opt/java/openjdk-8
ENV JAVA11_HOME=/opt/java/openjdk-11
ENV JAVA17_HOME=/opt/java/openjdk-17