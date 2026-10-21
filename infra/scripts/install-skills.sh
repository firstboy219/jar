#!/usr/bin/env bash
# Teach Hermes skills (SKILL.md, the same open format Claude uses). Idempotent; never touches skills
# Hermes wrote itself. Sources (pinned):
#   infra/hermes/skills/*             JARVIS' own skills (Indonesian context, self-development/repair)
#   anthropics/skills                 Apache-2.0 skills only — the docx/pdf/pptx/xlsx skills are
#                                     proprietary ("may not reproduce or copy"), so they are NOT installed
#   obra/superpowers                  MIT engineering workflow skills (minus the "use before every reply" meta ones)
#   Hermes optional-skills            curated subset bundled in the Hermes image (no jailbreak, GPU or paid-account skills)
set -euo pipefail
cd "$(dirname "$0")/.."
DEST=data/hermes/skills
ANTHROPIC_SHA=dbd4588f9e1033efb41dad4bef2f7947c8993d44
SUPERPOWERS_SHA=b739a8af570e10a95898f2bdf6cec97467fa6c12
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$DEST"

install_dir() { # src dest-category name
  local src=$1 cat=$2 name=$3
  [[ -f $src/SKILL.md ]] || { echo "skip $name (no SKILL.md)"; return; }
  rm -rf "${DEST:?}/$cat/$name"; mkdir -p "$DEST/$cat"
  cp -r "$src" "$DEST/$cat/$name"
  echo "ok   $cat/$name"
}

for d in hermes/skills/*/; do install_dir "$d" jarvis "$(basename "$d")"; done

fetch() { # repo sha dir
  git -c advice.detachedHead=false clone -q --filter=blob:none "https://github.com/$1.git" "$TMP/$3"
  git -C "$TMP/$3" checkout -q "$2"
}
fetch anthropics/skills "$ANTHROPIC_SHA" anthropic
for s in algorithmic-art brand-guidelines canvas-design claude-api doc-coauthoring frontend-design internal-comms \
         mcp-builder skill-creator slack-gif-creator theme-factory web-artifacts-builder webapp-testing; do
  install_dir "$TMP/anthropic/skills/$s" claude "$s"
done
fetch obra/superpowers "$SUPERPOWERS_SHA" superpowers
for s in brainstorming dispatching-parallel-agents executing-plans finishing-a-development-branch receiving-code-review \
         requesting-code-review subagent-driven-development systematic-debugging test-driven-development \
         using-git-worktrees verification-before-completion writing-plans writing-skills; do
  install_dir "$TMP/superpowers/skills/$s" superpowers "$s"
done
# brainstorming insists on a dialogue before ANY creative work; for JARVIS that is only right for big builds.
sed -i '0,/^description:/s|^description:.*|description: "For larger features or projects only (not quick tasks): explore intent, requirements and design with the owner before building."|' \
  "$DEST/superpowers/brainstorming/SKILL.md"

docker cp -q jarvis-brain:/opt/hermes/optional-skills "$TMP/optional"
for s in communication/one-three-one-rule creative/concept-diagrams creative/excalidraw creative/sketch \
         creative/creative-ideation creative/meme-generation creative/social-media-content-calendar creative/simple-english \
         creative/archify data-science/jupyter-notebook devops/watchers devops/setup-wizard-generator \
         dogfood/adversarial-ux-test finance/3-statement-model finance/comps-analysis finance/dcf-model finance/excel-author \
         finance/pptx-author finance/stocks health/fitness-nutrition mcp/fastmcp mcp/mcporter mlops/inference/llama-cpp \
         mlops/qdrant mlops/whisper mlops/instructor productivity/decision-questionnaire productivity/live-dashboard \
         productivity/memento-flashcards productivity/property-listings research/duckduckgo-search research/rss-feeds \
         research/blogwatcher research/domain-intel research/qmd software-development/ast-grep software-development/code-wiki \
         software-development/grill-me software-development/rest-graphql-debug software-development/subagent-driven-development \
         software-development/pr-lens web-development/har-derived-api-client web-development/publish-site \
         autonomous-ai-agents/dynamic-workflow security/oss-forensics; do
  install_dir "$TMP/optional/$s" "${s%%/*}" "$(basename "$s")"
done

chown -R "$(stat -c %u:%g data/hermes)" "$DEST"
echo "skills: $(find "$DEST" -name SKILL.md | wc -l) total"
