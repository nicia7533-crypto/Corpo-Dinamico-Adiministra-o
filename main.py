r"""
main.py
-------
Ponto de entrada do Corpo Dinamico.

IMPORTANTE (versao de diagnostico): este arquivo abre com uma janela de
console visivel de proposito. Se algo der errado, o erro aparece na tela
em vez de o programa simplesmente fechar sem avisar nada - foi exatamente
isso que aconteceu nas tentativas anteriores, e sem ver o erro de verdade
eu nao tenho como saber o que corrigir. Depois que confirmarmos que abre
certinho, e facil esconder essa janela de novo.

Sequencia de inicializacao:
  1. Garantir que a pasta de dados (%LOCALAPPDATA%\CorpoDinamico) existe.
  2. Impedir duas instancias ao mesmo tempo.
  3. Rodar migrations (com backup automatico se ja existir banco).
  4. Semear configuracoes padrao.
  5. Aplicar inativacao automatica por inadimplencia prolongada.
  6. Subir o servidor Flask local (so em 127.0.0.1).
  7. Abrir o navegador padrao apontando pra esse servidor.
"""

import os
import sys
import time
import traceback
import threading
import socket
import webbrowser


def _pause_antes_de_fechar():
    """Mantem a janela de console aberta se algo der errado, para o
    usuario conseguir ler e me passar a mensagem exata de erro."""
    try:
        input("\nPressione ENTER para fechar esta janela...")
    except Exception:
        pass


def main():
    from app.paths import ensure_all_dirs, CONFIG_DIR
    from app.logger import log_info, log_error, log_warning

    ensure_all_dirs()
    lock_file = os.path.join(CONFIG_DIR, ".instance.lock")

    # ---- trava de instancia unica ----
    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            print("O Corpo Dinamico ja esta aberto em outra janela.")
            print("Feche a outra janela antes de abrir uma nova.")
            _pause_antes_de_fechar()
            return
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            log_warning("Lock antigo sem processo vivo - liberando.")
    with open(lock_file, "w") as f:
        f.write(str(os.getpid()))

    try:
        log_info("=" * 60)
        log_info("Iniciando Corpo Dinamico...")
        print("Iniciando o Corpo Dinamico, aguarde um instante...")

        # ---- sequencia de inicializacao do banco ----
        from app.db import check_integrity
        from app.paths import DATABASE_PATH
        db_existed_before = os.path.exists(DATABASE_PATH)

        if db_existed_before:
            ok, detail = check_integrity()
            if not ok:
                log_error(f"Banco existente falhou na verificacao de integridade: {detail}")
            else:
                from app.backup_service import create_backup
                try:
                    create_backup(user_id=None, reason="automatico_pre_inicializacao")
                    log_info("Backup automatico de seguranca criado.")
                except Exception as exc:
                    log_error("Falha ao criar backup automatico (seguindo mesmo assim)", exc)

        from app.migrations_runner import run_migrations
        run_migrations()

        from app import settings_service
        settings_service.seed_defaults()

        if db_existed_before:
            from app import finance_service
            try:
                finance_service.apply_automatic_inactivations(user_id=None)
            except Exception as exc:
                log_error("Falha ao aplicar inativacao automatica", exc)

        from app.backup_service import reconcile_backup_log
        reconcile_backup_log(user_id=None)

        # ---- sobe o servidor local ----
        from app.web import create_app
        flask_app = create_app()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        server_thread = threading.Thread(
            target=lambda: flask_app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
            daemon=True,
        )
        server_thread.start()
        time.sleep(1.0)

        # ---- fila de envio de comprovantes por e-mail (roda sozinha, em segundo plano) ----
        from app import email_queue
        EMAIL_QUEUE_INTERVAL_SECONDS = 60

        def _loop_fila_email():
            while True:
                try:
                    resultado = email_queue.process_once()
                    if resultado["enviados"] or resultado["erros"] or resultado["recuperados_travados"]:
                        log_info(f"Fila de comprovantes: {resultado}")
                except Exception as exc:
                    log_error("Erro inesperado no processamento da fila de comprovantes", exc)
                time.sleep(EMAIL_QUEUE_INTERVAL_SECONDS)

        threading.Thread(target=_loop_fila_email, daemon=True).start()
        log_info("Fila de comprovantes por e-mail iniciada em segundo plano.")

        url = f"http://127.0.0.1:{port}/"
        log_info(f"Servidor local iniciado em {url}")
        print(f"Sistema disponivel em: {url}")
        print("Abrindo no seu navegador padrao...")

        webbrowser.open(url)

        print()
        print("=" * 60)
        print("  CORPO DINAMICO ESTA RODANDO")
        print("  Deixe esta janela aberta enquanto usa o sistema.")
        print("  Para fechar o sistema, feche esta janela ou aperte Ctrl+C.")
        print("=" * 60)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nEncerrando...")

    except Exception:
        erro_completo = traceback.format_exc()
        try:
            log_error("Falha critica na inicializacao:\n" + erro_completo)
        except Exception:
            pass
        print("\n" + "=" * 60)
        print("  OCORREU UM ERRO AO INICIAR O CORPO DINAMICO")
        print("=" * 60)
        print(erro_completo)
        print("=" * 60)
        print("Copie o texto do erro acima e envie para o suporte.")
        _pause_antes_de_fechar()
    finally:
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("ERRO INESPERADO:")
        traceback.print_exc()
        try:
            input("\nPressione ENTER para fechar...")
        except Exception:
            pass
