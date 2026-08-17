<?php

/**
 * dovecot_ident — Geseidl Edition
 *
 * Forwards the real webmail client IP to Dovecot via the IMAP ID command
 * (x-originating-ip), so per-account network restrictions (allow_nets),
 * auth policy and login logging apply to the actual browser IP instead of
 * 127.0.0.1 (Roundcube connects to Dovecot over localhost).
 *
 * Requires on the Dovecot side:
 *     login_trusted_networks = 127.0.0.1 ::1
 *
 * Functional equivalent of corbosman/dovecot_ident (MIT). Roundcube core
 * sends the ID command pre-login whenever the storage 'ident' pref is set.
 */
class dovecot_ident extends rcube_plugin
{
    public $task = 'login|mail|settings|addressbook';

    public function init()
    {
        $this->add_hook('storage_connect', array($this, 'storage_connect'));
    }

    public function storage_connect($args)
    {
        $args['ident'] = array(
            'name'             => 'Roundcube',
            'version'          => RCUBE_VERSION,
            'php'              => PHP_VERSION,
            'x-originating-ip' => rcube_utils::remote_addr(),
        );

        return $args;
    }
}
