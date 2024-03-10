#!/bin/bash

search_plugins() {
    declare -a plugins=()
    declare -a urls=()
    while IFS= read -r line; do
        if [[ $line =~ "\"full_name\": \""(.*)"\"," ]]; then
            plugins+=("${BASH_REMATCH[1]}")
        elif [[ $line =~ "\"clone_url\": \""(.*)"\"," ]]; then
            urls+=("${BASH_REMATCH[1]}")
        fi
    done < "$1"

    selected_plugin=$(printf '%s\n' "${plugins[@]}" | fzf)

    for (( i=0; i<${#plugins[@]}; i++ )); do
        if [[ "${plugins[i]}" == "$selected_plugin" ]]; then
            selected_url="${urls[i]}"
            break
        fi
    done

    github_link="https://www.github.com/${selected_plugin}"

    echo "Selected plugin full name: $selected_plugin"
    echo "Selected plugin GitHub link: $github_link"
    # move that to clipboard
    echo "$selected_url" | xclip -selection clipboard
    

}

if [ -z "$1" ]; then
    echo "Usage: ./search_plugins.sh <json_file>"
    exit 1
fi
if [ ! -f "$1" ]; then
    echo "Error: JSON file '$1' not found."
    exit 1
fi

search_plugins "$1"
