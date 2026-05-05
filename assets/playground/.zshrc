PROMPT='%F{yellow}playground ->%f '

redis(){
    redis-cli -h redis
}

autoload -Uz compinit
compinit

source ~/.git.plugin.zsh