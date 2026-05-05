PROMPT='%F{yellow}hook ->%f '

smartgit(){
    basename $PWD >> /root/smartgit-control
}

autoload -Uz compinit
compinit

source ~/.git.plugin.zsh