PROMPT='%F{yellow}playground ->%f '

HISTFILE="/root/caches/.zsh_history_playground"
HISTSIZE=1000
SAVEHIST=1000
setopt appendhistory

redis(){
    redis-cli -h redis
}

autoload -Uz compinit
compinit

source ~/.git.plugin.zsh