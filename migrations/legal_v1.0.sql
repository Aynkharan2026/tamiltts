-- =============================================================================
-- Tamil TTS Studio -- Consent Text v1.0
-- 17488149 CANADA CORP. operating as VoxTN
-- Effective: 2026-03-03
-- =============================================================================

INSERT INTO consent_texts (id, version, effective_date, body_text, created_at)
VALUES (
    gen_random_uuid(),
    'v1.0',
    '2026-03-03T00:00:00Z',
    $LEGAL$
TAMIL TTS STUDIO - VOICE CONSENT & USAGE AGREEMENT
Version 1.0 | Effective Date: March 3, 2026
Issued by: 17488149 CANADA CORP. operating as VoxTN
209-5200 Finch Ave E, Toronto, Ontario, Canada
Contact: hello@voxtn.com

READ THIS AGREEMENT CAREFULLY BEFORE PROCEEDING.
By clicking "I Agree" or by approving a consent request, you agree to be
legally bound by all terms below.

------------------------------------------------------------------------------
CLAUSE 1 - VOICE OWNERSHIP DECLARATION
------------------------------------------------------------------------------

1.1  By uploading a voice sample to Tamil TTS Studio, you ("Voice Owner")
     declare under penalty of applicable law that:

     (a) The voice contained in the uploaded sample is your own biological
         voice, OR you are an authorized legal representative of the person
         whose voice is contained in the sample;

     (b) You have the full legal right, authority, and capacity to grant
         the permissions described in this Agreement;

     (c) The uploaded sample does not contain the voice of any minor
         (person under 18 years of age) without verified parental or
         guardian consent;

     (d) The uploaded sample does not infringe the intellectual property,
         privacy, or publicity rights of any third party.

1.2  You understand that making a false ownership declaration may constitute
     fraud, identity theft, or violation of applicable privacy laws including
     but not limited to PIPEDA (Canada), GDPR (EU), and equivalent statutes.

1.3  VoxTN reserves the right to permanently disable any voice model and
     suspend any account found to contain a fraudulent ownership declaration,
     without notice and without refund.

------------------------------------------------------------------------------
CLAUSE 2 - CONSENT AUTHORIZATION AGREEMENT
------------------------------------------------------------------------------

2.1  When you approve a consent request submitted by another registered user
     ("Requester"), you grant the Requester a limited, non-exclusive,
     revocable licence to use your voice model solely within Tamil TTS Studio
     for the purposes explicitly described at the time of the consent request.

2.2  This licence does not transfer ownership of your voice, your voice model,
     or any underlying biometric data to the Requester or to VoxTN.

2.3  Consent is recorded with: the version of this Agreement you accepted,
     your IP address at time of acceptance, the date and time of acceptance
     (UTC), your registered user ID or verified email address, and the
     specific voice model ID to which consent applies.

2.4  Consent granted under this Agreement applies only to the specific
     voice model ID identified in the consent request. It does not extend
     to any other voice model, current or future.

2.5  You may revoke consent at any time by accessing your account settings
     or contacting support@voxtn.com. Revocation takes effect immediately
     upon confirmation. All new generation requests using your voice model
     will be blocked at the point of job creation. Audio already generated
     prior to revocation is not retroactively deleted unless you separately
     request deletion under Clause 6.

------------------------------------------------------------------------------
CLAUSE 3 - PROHIBITED USES
------------------------------------------------------------------------------

3.1  The following uses of any voice model, generated audio, or any feature
     of Tamil TTS Studio are STRICTLY PROHIBITED:

     (a) Creating deepfakes -- any audio or media that falsely represents a
         real person as saying something they did not say;

     (b) Impersonation -- generating audio intended to deceive any person,
         institution, or automated system into believing they are
         communicating with a specific real individual;

     (c) Fraud -- using generated audio in any scheme to obtain money,
         property, credentials, or any benefit by deception;

     (d) Harassment -- generating audio for the purpose of harassing,
         threatening, intimidating, or humiliating any individual;

     (e) Non-consensual intimate audio -- generating audio of a sexual or
         intimate nature using any person's voice without their explicit
         written consent;

     (f) Political disinformation -- generating audio designed to interfere
         with democratic processes, spread electoral misinformation, or
         falsely attribute statements to public officials or candidates;

     (g) Circumventing security systems -- using generated audio to bypass
         voice-based authentication, biometric verification, or any
         security control;

     (h) Generating audio involving minors in any sexual, violent, or
         exploitative context.

3.2  Violation of any prohibition in Clause 3.1 will result in immediate
     account suspension, permanent voice model deletion, reporting to
     applicable law enforcement, and preservation of all logs for legal
     proceedings.

3.3  VoxTN cooperates fully with law enforcement agencies and will disclose
     all relevant records in response to valid legal process without prior
     notice to the account holder where disclosure would compromise
     an investigation.

------------------------------------------------------------------------------
CLAUSE 4 - REVOCATION RIGHTS
------------------------------------------------------------------------------

4.1  You have the unconditional right to revoke any consent you have granted
     at any time, for any reason, without penalty.

4.2  Revocation is effective immediately upon system confirmation. The system
     will block all new job creation requests that reference your voice model
     within seconds of revocation confirmation.

4.3  Revocation does not retroactively delete audio already generated and
     delivered to the Requester prior to the revocation timestamp. If you
     require deletion of previously generated audio, you must submit a
     separate deletion request under Clause 6.

4.4  Upon revocation, the Requester will receive a notification that consent
     has been withdrawn and that no further generation using your voice model
     is permitted.

4.5  VoxTN maintains an append-only audit log of all consent grants,
     modifications, and revocations. This log cannot be altered or deleted
     by any user and is retained for a minimum of 7 years.

------------------------------------------------------------------------------
CLAUSE 5 - DATA RETENTION POLICY
------------------------------------------------------------------------------

5.1  Voice samples uploaded to Tamil TTS Studio are stored in encrypted
     private storage (Cloudflare R2) and are never made publicly accessible.
     Signed access URLs are time-limited and scoped to the authorised user only.

5.2  Voice sample files are retained for the duration of your account's
     active status plus 90 days following account closure or voice model
     deletion, to allow for dispute resolution.

5.3  Generated audio files are retained for 7 days from the date of
     generation, after which they are automatically deleted from storage.
     Signed access URLs expire within the same 7-day window.

5.4  Consent records, ownership declarations, audit logs, and usage logs
     are retained for a minimum of 7 years regardless of account status,
     in compliance with applicable record-keeping obligations.

5.5  Usage tracking data (character counts, job counts) is retained for
     24 months and is used solely for billing, abuse detection, and
     service improvement.

5.6  You may request a copy of all personal data held about you by
     contacting hello@voxtn.com. We will respond within 30 days in
     compliance with PIPEDA and applicable privacy legislation.

------------------------------------------------------------------------------
CLAUSE 6 - VOICE MODEL DELETION POLICY
------------------------------------------------------------------------------

6.1  You may request deletion of your voice model at any time by:
     (a) Using the "Delete Voice Model" function in your account settings, or
     (b) Contacting hello@voxtn.com with your account email and voice model ID.

6.2  Upon deletion request:
     (a) Your voice model will be immediately disabled (no new jobs accepted);
     (b) The voice model will be deleted from ElevenLabs within 24 hours;
     (c) The original voice sample file will be deleted from storage
         within 72 hours;
     (d) All active consent authorizations referencing this voice model
         will be automatically revoked.

6.3  Deletion of a voice model does not delete the consent records,
     audit logs, or usage logs associated with it. These are retained
     under Clause 5.4.

6.4  Deletion of generated audio files on demand: if you are the Voice Owner
     and you believe audio was generated using your voice model without
     valid consent, contact support@voxtn.com with the job ID or relevant
     details. We will investigate and delete within 72 hours if the claim
     is substantiated.

6.5  VoxTN may delete any voice model at its sole discretion if it determines
     the model violates this Agreement or applicable law. Notice will be
     provided except where doing so would compromise a legal investigation.

------------------------------------------------------------------------------
CLAUSE 7 - LIABILITY LIMITATION
------------------------------------------------------------------------------

7.1  TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, VOXTN AND
     17488149 CANADA CORP. SHALL NOT BE LIABLE FOR ANY INDIRECT,
     INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES ARISING
     FROM YOUR USE OF VOICE CLONING FEATURES, INCLUDING BUT NOT LIMITED
     TO DAMAGES ARISING FROM UNAUTHORISED USE OF GENERATED AUDIO,
     THIRD-PARTY MISUSE, OR SERVICE INTERRUPTIONS.

7.2  VoxTN's total aggregate liability to you for any claim arising under
     this Agreement shall not exceed the total fees paid by you to VoxTN
     in the 12 months preceding the claim.

7.3  VoxTN is not liable for the actions of third parties who obtain access
     to generated audio through means outside VoxTN's control, including
     but not limited to data breaches caused by the user's own security
     failures.

7.4  Nothing in this clause limits VoxTN's liability for death or personal
     injury caused by negligence, fraud, or any liability that cannot be
     excluded by applicable law.

------------------------------------------------------------------------------
CLAUSE 8 - PLATFORM MISUSE ENFORCEMENT
------------------------------------------------------------------------------

8.1  VoxTN operates an automated and manual abuse detection system that
     monitors usage patterns, generation volumes, and content flags.

8.2  Upon detection of potential misuse, VoxTN may, at its discretion:
     (a) Flag the account for manual review (abuse_flag = true);
     (b) Temporarily suspend generation capabilities pending review;
     (c) Permanently suspend the account;
     (d) Delete all voice models and generated audio associated with
         the account;
     (e) Report the activity to applicable law enforcement.

8.3  Users subject to enforcement action may appeal by contacting
     hello@voxtn.com within 14 days of notification. VoxTN will respond
     within 10 business days.

8.4  VoxTN reserves the right to modify, throttle, or terminate service to
     any account at any time if continued service poses a legal,
     reputational, or technical risk to the platform.

------------------------------------------------------------------------------
CLAUSE 9 - AUDIO REDISTRIBUTION POLICY
------------------------------------------------------------------------------

9.1  Audio generated using Tamil TTS Studio using standard Edge-TTS voices
     (non-cloned) may be used by the generating user for personal, commercial,
     or editorial purposes, subject to the Microsoft Edge-TTS terms of service
     and applicable copyright law.

9.2  Audio generated using a cloned voice model may only be redistributed
     with the explicit written consent of the Voice Owner. The Requester is
     solely responsible for ensuring they hold valid consent before any
     redistribution.

9.3  The following redistributions are prohibited regardless of consent:
     (a) Redistribution that violates Clause 3 (Prohibited Uses);
     (b) Sale or sublicensing of cloned voice audio without a separate
         written agreement with VoxTN;
     (c) Use of cloned voice audio to train, fine-tune, or evaluate any AI
         or machine learning model without the Voice Owner's explicit written
         consent and VoxTN's written approval.

9.4  Audio generated on the Free tier includes an audio watermark
     ("Generated by VoxTN Online."). Removal, suppression, or circumvention
     of this watermark is prohibited and constitutes a material breach of
     this Agreement.

9.5  VoxTN retains no ownership over audio generated by users but reserves
     the right to use anonymised usage metadata (not audio content) for
     service improvement and analytics.

------------------------------------------------------------------------------
CLAUSE 10 - GOVERNING LAW & DISPUTE RESOLUTION
------------------------------------------------------------------------------

10.1 This Agreement is governed by the laws of the Province of Ontario
     and the federal laws of Canada applicable therein.

10.2 Any dispute arising from this Agreement that cannot be resolved
     informally shall be submitted to binding arbitration in Toronto,
     Ontario under the Arbitration Act, 1991 (Ontario).

10.3 Nothing in this clause prevents either party from seeking injunctive
     or emergency relief from a court of competent jurisdiction where
     irreparable harm is at risk.

------------------------------------------------------------------------------

BY CLICKING "I AGREE", APPROVING A CONSENT REQUEST, OR UPLOADING A
VOICE SAMPLE, YOU CONFIRM THAT:

  [ ] I have read and understood this Agreement in full.
  [ ] I am 18 years of age or older.
  [ ] I have the legal authority to enter into this Agreement.
  [ ] The voice sample I am uploading or authorising belongs to me or
      I have verified legal authority to use it.
  [ ] I understand that this consent is recorded with my IP address,
      timestamp, and account details.

------------------------------------------------------------------------------
$LEGAL$,
    NOW()
);
