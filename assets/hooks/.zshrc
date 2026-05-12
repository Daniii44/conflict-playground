PROMPT='%F{yellow}hook ->%f '

HISTFILE="/root/caches/.zsh_history_hooks"
HISTSIZE=1000
SAVEHIST=1000
setopt appendhistory

smartgit(){
    basename $PWD >> /root/smartgit-control
}

show-conflict(){
    merge_commit="${$(pwd)##*-}"
    git merge-tree $merge_commit^1 $merge_commit^2
}

show-resolution(){
    merge_commit="${$(pwd)##*-}"
    git merge-tree -z $merge_commit^1 $merge_commit^2 | read -r -d '' confliced_tree
    git diff-tree -p $confliced_tree $merge_commit
    git diff-tree $confliced_tree $merge_commit
}

autoload -Uz compinit
compinit

source ~/.git.plugin.zsh