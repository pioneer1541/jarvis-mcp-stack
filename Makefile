.PHONY: post-dev-eval phase-eval install-hooks

post-dev-eval:
	./scripts/post_dev_eval.sh

phase-eval:
	./scripts/phase_eval.sh

install-hooks:
	./scripts/install_git_hooks.sh
