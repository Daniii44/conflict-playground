PROMPT='%F{yellow}hook ->%f '

HISTFILE="/root/caches/.zsh_history_hooks"
HISTSIZE=1000
SAVEHIST=1000
setopt appendhistory

smartgit(){
    basename $PWD >> /root/smartgit-control
}

autoload -Uz compinit
compinit

source ~/.git.plugin.zsh